"""
NetTap IoT Monitor API Routes

Registers IoT device monitoring endpoints with the aiohttp application.
"""

import asyncio
import functools
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from aiohttp import web

from storage.exact_terms import PartialResultsError
from api.error_replies import incomplete
from api.time_range import BUCKET_TABLE, parse_time_range, slot_interval
from services.iot_monitor import IoTMonitor
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.iot")

_DEFAULT_RANGE_HOURS = 24

_EXECUTOR_KEY = "iot_executor"


async def _run_iot(request: web.Request, fn, *args, **kwargs):
    """Run a sync IoTMonitor call on the IoT API's single-worker executor.

    One worker keeps the calls off the event loop but never concurrent:
    IoTMonitor mutates and iterates shared device/baseline dicts unlocked.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        request.app[_EXECUTOR_KEY], functools.partial(fn, *args, **kwargs)
    )


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """'from'/'to' as ISO timestamps, defaulting to the last 24 hours; unreadable is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to (e.g. now-5m) silently became the
    # default window, so the Infrastructure page divided 24 h of events by 5 min
    # """Extract 'from' and 'to' query parameters as ISO timestamps."""
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    # default_to = now.isoformat()
    #
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    #
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # if raw_to:
    #     try:
    #         datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_to = ""
    #
    # return (raw_from or default_from, raw_to or default_to)
    # OLD CODE END
    return parse_time_range(request, timedelta(hours=_DEFAULT_RANGE_HOURS))


async def handle_iot_devices(request: web.Request) -> web.Response:
    """GET /api/iot/devices"""
    iot: IoTMonitor = request.app["iot_monitor"]
    # OLD CODE START — sync IoTMonitor call blocked the event loop
    # devices = iot.get_iot_devices()
    # OLD CODE END
    devices = await _run_iot(request, iot.get_iot_devices)
    return web.json_response({"devices": devices, "count": len(devices)})


async def handle_device_baseline(request: web.Request) -> web.Response:
    """GET /api/iot/devices/{mac}/baseline"""
    mac = request.match_info["mac"]
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    # OLD CODE START — sync IoTMonitor call blocked the event loop
    # baseline = iot.get_device_baseline(mac)
    # OLD CODE END
    baseline = await _run_iot(request, iot.get_device_baseline, mac)
    if baseline is None:
        # Try to build one
        try:
            # OLD CODE START — sync IoTMonitor call blocked the event loop
            # baseline = iot.build_baseline(mac, excluded_ips=excluded_ips_list)
            # OLD CODE END
            baseline = await _run_iot(
                request, iot.build_baseline, mac, excluded_ips=excluded_ips_list
            )
        except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
            return incomplete("IoT", exc)
        except Exception as exc:
            logger.error("Failed to build baseline for %s: %s", mac, exc)
            return web.json_response(
                {"error": f"Failed to build baseline: {exc}"}, status=500
            )

    return web.json_response({"mac": mac, "baseline": baseline})


async def handle_iot_anomalies(request: web.Request) -> web.Response:
    """GET /api/iot/anomalies?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # anomalies = iot.get_anomalies(from_ts, to_ts, excluded_ips=excluded_ips_list)
        # OLD CODE END
        anomalies = await _run_iot(
            request, iot.get_anomalies, from_ts, to_ts, excluded_ips=excluded_ips_list
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("IoT anomaly detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "anomalies": anomalies,
            "count": len(anomalies),
        }
    )


async def handle_fleet_summary(request: web.Request) -> web.Response:
    """GET /api/iot/fleet-summary"""
    iot: IoTMonitor = request.app["iot_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_fleet_summary(from_ts, to_ts, excluded_ips=excluded_ips_list)
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_fleet_summary,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Fleet summary failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


# OLD CODE START — NET-174: no page or script called this route, and the device it added was
# dropped on the next range request (discovery rebuilds the IoT set).
# async def handle_classify_device(request: web.Request) -> web.Response:
#     """POST /api/iot/devices/{mac}/classify"""
#     mac = request.match_info["mac"]
#     iot: IoTMonitor = request.app["iot_monitor"]
#
#     try:
#         body = await request.json()
#     except Exception:
#         body = {}
#
#     # OLD CODE START — sync IoTMonitor call blocked the event loop
#     # is_iot = iot.classify_as_iot(mac, body)
#     # OLD CODE END
#     is_iot = await _run_iot(request, iot.classify_as_iot, mac, body)
#
#     return web.json_response(
#         {
#             "mac": mac,
#             "is_iot": is_iot,
#             "message": f"Device {mac} {'classified as IoT' if is_iot else 'not classified as IoT'}",
#         }
#     )
# OLD CODE END


async def handle_privacy_report(request: web.Request) -> web.Response:
    """GET /api/iot/privacy-report?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_privacy_report(from_ts, to_ts, excluded_ips=excluded_ips_list)
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_privacy_report,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Privacy report failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


async def handle_communication_map(request: web.Request) -> web.Response:
    """GET /api/iot/devices/{mac}/communication-map?from=&to="""
    mac = request.match_info["mac"]
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_communication_map(
        #     mac, from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_communication_map,
            mac,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Communication map failed for %s: %s", mac, exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


async def handle_activity_timeline(request: web.Request) -> web.Response:
    """GET /api/iot/devices/{mac}/activity-timeline?from=&to=&interval="""
    mac = request.match_info["mac"]
    from_ts, to_ts = _parse_time_range(request)
    # NET-249: the bucket table, whose 1h was the only bucket before
    interval = slot_interval(request, from_ts, to_ts, BUCKET_TABLE, "1h")
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_activity_timeline(
        #     mac, from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_activity_timeline,
            mac,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
            interval=interval,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Activity timeline failed for %s: %s", mac, exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


async def handle_protocol_audit(request: web.Request) -> web.Response:
    """GET /api/iot/protocol-audit?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_protocol_audit(from_ts, to_ts, excluded_ips=excluded_ips_list)
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_protocol_audit,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Protocol audit failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


async def handle_network_isolation(request: web.Request) -> web.Response:
    """GET /api/iot/network-isolation?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_network_isolation(
        #     from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_network_isolation,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Network isolation analysis failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


async def handle_manufacturer_profiles(request: web.Request) -> web.Response:
    """GET /api/iot/manufacturer-profiles?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE START — sync IoTMonitor call blocked the event loop
        # result = iot.get_manufacturer_profiles(
        #     from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        result = await _run_iot(
            request,
            iot.get_manufacturer_profiles,
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
        )
    except PartialResultsError as exc:  # a capped scan or a part reply (NET-237)
        return incomplete("IoT", exc)
    except Exception as exc:
        logger.error("Manufacturer profiles failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(result)


async def _shutdown_iot_executor(app: web.Application) -> None:
    app[_EXECUTOR_KEY].shutdown(wait=False, cancel_futures=True)


def register_iot_routes(app: web.Application, storage: StorageManager) -> None:
    """Register IoT monitoring API routes."""
    # OLD CODE: iot_monitor = IoTMonitor(client=storage._client) (NET-200: owner names)
    custom = app.get("device_custom")
    iot_monitor = IoTMonitor(
        client=storage._client, owner_name=custom.name_for if custom else None
    )
    app["iot_monitor"] = iot_monitor
    app[_EXECUTOR_KEY] = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="nettap-iot"
    )
    app.on_cleanup.append(_shutdown_iot_executor)

    app.router.add_get("/api/iot/devices", handle_iot_devices)
    app.router.add_get("/api/iot/devices/{mac}/baseline", handle_device_baseline)
    app.router.add_get(
        "/api/iot/devices/{mac}/communication-map", handle_communication_map
    )
    app.router.add_get(
        "/api/iot/devices/{mac}/activity-timeline", handle_activity_timeline
    )
    app.router.add_get("/api/iot/anomalies", handle_iot_anomalies)
    app.router.add_get("/api/iot/fleet-summary", handle_fleet_summary)
    app.router.add_get("/api/iot/privacy-report", handle_privacy_report)
    app.router.add_get("/api/iot/protocol-audit", handle_protocol_audit)
    app.router.add_get("/api/iot/network-isolation", handle_network_isolation)
    app.router.add_get("/api/iot/manufacturer-profiles", handle_manufacturer_profiles)
    # OLD CODE START — NET-174: unused, and its result didn't survive a range change
    # app.router.add_post("/api/iot/devices/{mac}/classify", handle_classify_device)
    # logger.info("IoT monitoring API routes registered (11 endpoints)")
    # OLD CODE END
    logger.info("IoT monitoring API routes registered (10 endpoints)")
