"""PyPI JSON API client for artifact tracking."""

import httpx


async def get_pypi_version(package_name: str) -> dict:
    """Query PyPI for the latest version of a package."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            return {"error": f"Package '{package_name}' not found on PyPI"}
        if resp.status_code != 200:
            return {"error": f"PyPI returned {resp.status_code}"}
        data = resp.json()
        return {
            "name": package_name,
            "version": data["info"]["version"],
        }


async def check_version_published(package_name: str, version: str) -> dict:
    """Check if a specific version is published on PyPI."""
    url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        return {
            "name": package_name,
            "version": version,
            "published": resp.status_code == 200,
        }
