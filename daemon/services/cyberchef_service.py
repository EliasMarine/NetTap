"""
NetTap CyberChef Service — Container status and recipe helpers.

CyberChef is a fully client-side web application served by nginx.
This service only monitors the container health and provides
pre-built recipe URLs for common forensic operations.
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger("nettap.cyberchef")

CYBERCHEF_CONTAINER = "nettap-cyberchef"
CYBERCHEF_INTERNAL_URL = "http://nettap-cyberchef:8443"


@dataclass
class CyberChefRecipe:
    """A pre-built CyberChef recipe with URL fragment."""
    name: str
    description: str
    category: str  # "decode", "crypto", "network", "forensic"
    recipe_fragment: str  # URL hash fragment for CyberChef


# Pre-built recipes for common network forensics operations
BUILTIN_RECIPES: list[CyberChefRecipe] = [
    CyberChefRecipe(
        name="Base64 Decode",
        description="Decode Base64 encoded data (common in HTTP payloads and email)",
        category="decode",
        recipe_fragment="#recipe=From_Base64('A-Za-z0-9%2B/%3D',true,false)",
    ),
    CyberChefRecipe(
        name="URL Decode",
        description="Decode URL-encoded (percent-encoded) strings",
        category="decode",
        recipe_fragment="#recipe=URL_Decode()",
    ),
    CyberChefRecipe(
        name="Hex Decode",
        description="Convert hex-encoded data to raw bytes",
        category="decode",
        recipe_fragment="#recipe=From_Hex('Auto')",
    ),
    CyberChefRecipe(
        name="Extract URLs",
        description="Extract all URLs from text or binary data",
        category="forensic",
        recipe_fragment="#recipe=Extract_URLs(false)",
    ),
    CyberChefRecipe(
        name="Extract IP Addresses",
        description="Extract all IPv4 and IPv6 addresses from data",
        category="network",
        recipe_fragment="#recipe=Extract_IP_addresses(true,true,true)",
    ),
    CyberChefRecipe(
        name="Extract Email Addresses",
        description="Extract email addresses from data",
        category="forensic",
        recipe_fragment="#recipe=Extract_email_addresses(false)",
    ),
    CyberChefRecipe(
        name="Defang URL",
        description="Defang URLs for safe sharing (hxxps://)",
        category="network",
        recipe_fragment="#recipe=Defang_URL(true,true,true,'Valid domains and full URLs')",
    ),
    CyberChefRecipe(
        name="Parse TLS Certificate",
        description="Parse and display X.509 certificate details",
        category="crypto",
        recipe_fragment="#recipe=Parse_X.509_certificate('PEM')",
    ),
    CyberChefRecipe(
        name="Entropy Analysis",
        description="Calculate Shannon entropy to detect encryption/compression",
        category="forensic",
        recipe_fragment="#recipe=Entropy('Shannon%20scale')",
    ),
    CyberChefRecipe(
        name="DNS Packet Decode",
        description="Decode raw DNS packet data",
        category="network",
        recipe_fragment="#recipe=From_Hex('Auto')&input=",
    ),
]


class CyberChefService:
    """Manages CyberChef container status and recipe helpers."""

    def __init__(self, base_url: str = CYBERCHEF_INTERNAL_URL):
        self.base_url = base_url

    async def is_available(self) -> dict:
        """Check if the CyberChef container is running."""
        try:
            cmd = [
                "docker", "inspect", "--format",
                "{{.State.Running}}", CYBERCHEF_CONTAINER,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            running = stdout_b.decode().strip().lower() == "true"
            return {
                "available": running,
                "container_running": running,
                "container_name": CYBERCHEF_CONTAINER,
                "url": self.base_url if running else None,
            }
        except Exception as e:
            logger.error("Failed to check CyberChef availability: %s", e)
            return {
                "available": False,
                "container_running": False,
                "container_name": CYBERCHEF_CONTAINER,
                "url": None,
                "error": str(e),
            }

    def get_recipes(self, category: str = "") -> list[dict]:
        """Get pre-built CyberChef recipes, optionally filtered by category."""
        recipes = BUILTIN_RECIPES
        if category:
            recipes = [r for r in recipes if r.category == category]
        return [
            {
                "name": r.name,
                "description": r.description,
                "category": r.category,
                "url": f"{self.base_url}/{r.recipe_fragment}",
            }
            for r in recipes
        ]

    def build_recipe_url(self, recipe_fragment: str, input_data: str = "") -> str:
        """Build a full CyberChef URL with a recipe and optional input data."""
        url = f"{self.base_url}/{recipe_fragment}"
        if input_data:
            # CyberChef accepts input via the &input= parameter (base64 encoded)
            import base64
            encoded = base64.b64encode(input_data.encode()).decode()
            if "&input=" not in url:
                url += f"&input={encoded}"
            else:
                url = url.replace("&input=", f"&input={encoded}")
        return url

    def get_status(self) -> dict:
        """Return service info (sync, for embedding in other status calls)."""
        return {
            "service": "cyberchef",
            "base_url": self.base_url,
            "recipe_count": len(BUILTIN_RECIPES),
            "categories": list(set(r.category for r in BUILTIN_RECIPES)),
        }
