from opensoul.comfy_client import base_url, sdk_status


def test_sdk_status_keys():
    s = sdk_status()
    assert "COMFY_BASE_URL" in s
    assert "comfy_sdk_importable" in s
    assert base_url().startswith("http")
