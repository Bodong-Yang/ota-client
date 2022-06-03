import pytest


@pytest.fixture
def patch(mocker):
    import random
    from app.ota_client import OtaClient
    from app.ota_client_call import OtaClientCall
    from app.ota_client_service import OtaClientServiceV2

    mocker.patch.object(OtaClient, "__init__", return_value=None)
    mocker.patch.object(OtaClientCall, "__init__", return_value=None)
    mocker.patch.object(OtaClientServiceV2, "__init__", return_value=None)
    mocker.patch("app.main.service_start", return_value=None)
    mocker.patch("app.main.service_wait_for_termination", return_value=None)
    mocker.patch("app.main.os.getpid", lambda: random.getrandbits(64))


def test_main(patch, mocker):
    from app.main import main

    main()


def test_main_with_version(patch, mocker, tmp_path, caplog):
    from app.main import main

    version = tmp_path / "version.txt"
    version.write_text("d3b6bdb | 2021-10-27 09:36:48 +0900 | Initial commit")
    mocker.patch("app.main.VERSION_FILE", version)

    main()
    assert caplog.records[0].msg == "started"
    assert (
        caplog.records[1].msg == "d3b6bdb | 2021-10-27 09:36:48 +0900 | Initial commit"
    )
