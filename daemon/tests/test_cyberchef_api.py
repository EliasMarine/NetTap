"""POST /api/cyberchef/url returns a browser link under /cyberchef/ and rejects other targets."""

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.cyberchef import register_cyberchef_routes
from services.cyberchef_service import CyberChefService


class TestCyberChefUrlEndpoint(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_cyberchef_routes(app, CyberChefService())
        return app

    async def test_recipe_list_carries_the_fragment_the_page_posts_back(self):
        resp = await self.client.get("/api/cyberchef/recipes")
        recipe = (await resp.json())["recipes"][0]
        resp = await self.client.post(
            "/api/cyberchef/url",
            json={"recipe_fragment": recipe["recipe_fragment"], "input_data": "hi"},
        )
        self.assertEqual(resp.status, 200)
        self.assertTrue((await resp.json())["url"].startswith("/cyberchef/#recipe="))

    async def test_non_recipe_fragment_is_rejected(self):
        for fragment in ["../../logout", "https://evil.example/", "#input=abc"]:
            resp = await self.client.post(
                "/api/cyberchef/url", json={"recipe_fragment": fragment}
            )
            self.assertEqual(resp.status, 400, fragment)

    async def test_missing_fragment_is_rejected(self):
        resp = await self.client.post("/api/cyberchef/url", json={"input_data": "x"})
        self.assertEqual(resp.status, 400)

    async def test_non_text_input_is_rejected(self):
        resp = await self.client.post(
            "/api/cyberchef/url",
            json={"recipe_fragment": "#recipe=URL_Decode()", "input_data": ["x"]},
        )
        self.assertEqual(resp.status, 400)
