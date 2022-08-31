import asyncio
import pytest
import pytest_mock
import time
import typing
from pathlib import Path
from typing import List
from app.proto import wrapper

from tests.utils import DummySubECU
from tests.conftest import ThreadpoolExecutorFixtureMixin, TestConfiguration as cfg

import logging

logger = logging.getLogger(__name__)


class _DummySubECUsGroup:
    def __init__(self, ecu_id_list: List[str]) -> None:
        self._ecu_dict = {ecu_id: DummySubECU(ecu_id=ecu_id) for ecu_id in ecu_id_list}
        self._if_received_update = {ecu_id: False for ecu_id in ecu_id_list}

    async def start_update(self, ecu_id, *args, request, **kwargs):
        logger.info(f"update request for {ecu_id=}")
        self._ecu_dict[ecu_id].start()
        self._if_received_update[ecu_id] = True
        return wrapper.UpdateResponse(
            ecu=[
                wrapper.v2.UpdateResponseEcu(
                    ecu_id=ecu_id,
                    result=wrapper.FailureType.NO_FAILURE.value,
                )
            ]
        )

    def if_all_subecus_received_update(self):
        _res = True
        for _, v in self._if_received_update.items():
            _res &= v
        return _res

    def start_update_all(self):
        for ecu_id, ecu in self._ecu_dict.items():
            ecu.start()
            self._if_received_update[ecu_id] = True

    async def get_status(self, ecu_id, *args, **kwargs):
        return self._ecu_dict[ecu_id].status()


class TestOtaProxyWrapper:
    @pytest.fixture
    def mock_cfg(self, tmp_path: Path, mocker: pytest_mock.MockerFixture):
        from app.proxy_info import ProxyInfo
        from ota_proxy.config import Config

        _proxy_cfg = ProxyInfo()
        _proxy_cfg.enable_local_ota_proxy = True
        _proxy_cfg.gateway = False  # disable HTTPS
        mocker.patch(f"{cfg.OTACLIENT_STUB_MODULE_PATH}.proxy_cfg", _proxy_cfg)

        ota_cache_dir = tmp_path / "ota-cache"
        ota_cache_dir.mkdir()
        _ota_proxy_cfg = Config()
        _ota_proxy_cfg.BASE_DIR = str(ota_cache_dir)
        mocker.patch(f"{cfg.OTAPROXY_MODULE_PATH}.ota_cache.cfg", _ota_proxy_cfg)

    @pytest.fixture
    def ota_proxy_instance(self, mocker: pytest_mock.MockerFixture, mock_cfg):
        from app.ota_client_stub import OtaProxyWrapper

        _ota_proxy_wrapper = OtaProxyWrapper()
        self._ota_proxy_instance = _ota_proxy_wrapper
        try:
            yield _ota_proxy_wrapper.start(
                init_cache=True,
                wait_on_scrub=False,
            )
        finally:
            _ota_proxy_wrapper.stop()

    def test_OtaProxyWrapper(self, ota_proxy_instance):
        # TODO: ensure that the ota_proxy is launched and functional
        #       by downloading a file with proxy
        assert self._ota_proxy_instance.is_running()
        assert (
            self._ota_proxy_instance._server_p
            and self._ota_proxy_instance._server_p.is_alive()
        )


class Test_UpdateSession(ThreadpoolExecutorFixtureMixin):
    THTREADPOOL_EXECUTOR_PATCH_PATH = f"{cfg.OTACLIENT_STUB_MODULE_PATH}"
    LOCAL_UPDATE_TIME_COST = 1
    SUBECU_UPDATE_TIME_COST = 2

    @pytest.fixture(autouse=True)
    def mock_setup(self, mocker: pytest_mock.MockerFixture, setup_executor):
        from app.ota_client import OTAUpdateFSM

        _ota_update_fsm = typing.cast(OTAUpdateFSM, mocker.MagicMock(spec=OTAUpdateFSM))
        _ota_update_fsm.stub_wait_for_local_update = mocker.MagicMock(
            wraps=self._local_update_waiter
        )
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.OTAUpdateFSM",
            return_value=_ota_update_fsm,
        )
        self._fsm = _ota_update_fsm

    def _local_update_waiter(self):
        time.sleep(self.LOCAL_UPDATE_TIME_COST)
        return True

    async def _subecu_update(self):
        await asyncio.sleep(self.SUBECU_UPDATE_TIME_COST)
        return True

    async def test_my_ecu_update_tracker(self):
        from app.ota_client_stub import _UpdateSession

        await _UpdateSession.my_ecu_update_tracker(
            fsm=self._fsm,
            executor=self._executor,
        )
        self._fsm.stub_wait_for_local_update.assert_called_once()

    async def test_update_tracker(self):
        from app.ota_client_stub import _UpdateSession

        # launch update session
        _update_session = _UpdateSession(executor=self._executor)

        ###### prepare tracking coroutine ######
        _my_ecu_tracking_task = _update_session.my_ecu_update_tracker(
            fsm=self._fsm,
            executor=self._executor,
        )
        _subecu_tracking_task = self._subecu_update()

        await _update_session.start(None)
        await _update_session.update_tracker(
            my_ecu_tracking_task=_my_ecu_tracking_task,
            subecu_tracking_task=_subecu_tracking_task,
        )

        ###### assert ######
        assert not _update_session.is_started()
        self._fsm.stub_wait_for_local_update.assert_called_once()
        self._fsm.stub_cleanup_finished.assert_called_once()


class Test_SubECUTracker:
    @pytest.fixture
    def setup_subecus(self):
        self._subecu_dict = {"p1": "", "p2": ""}
        self._subecs = _DummySubECUsGroup(list(self._subecu_dict.keys()))

    @pytest.fixture(autouse=True)
    def mock_setup(self, mocker: pytest_mock.MockerFixture, setup_subecus):
        from app.ota_client_call import OtaClientCall

        _ota_client_call = typing.cast(
            OtaClientCall, mocker.MagicMock(spec=OtaClientCall)
        )
        _ota_client_call.status_call = mocker.MagicMock(wraps=self._subecs.get_status)

        # patch
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.OtaClientCall", _ota_client_call
        )
        self._ota_client_call = _ota_client_call

    async def test__SubECUTracker(self):
        from app.ota_client_stub import _SubECUTracker

        self._subecs.start_update_all()
        _subecu_tracker = _SubECUTracker(self._subecu_dict)
        assert await _subecu_tracker.ensure_tracked_ecu_ready()


class TestOtaClientStub(ThreadpoolExecutorFixtureMixin):
    THTREADPOOL_EXECUTOR_PATCH_PATH = f"{cfg.OTACLIENT_STUB_MODULE_PATH}"
    # TODO: updater/rollback: test whether the all the subecus received update requests or not
    # TODO: status

    @pytest.fixture
    def setup_ecus(self):
        self._my_ecuid = "autoware"
        self._subecu_dict = {"p1": "", "p2": ""}
        self._subecs = _DummySubECUsGroup(list(self._subecu_dict.keys()))
        self._subecu_list_ecu_info = [
            {"ecu_id": "p1", "ip_addr": ""},
            {"ecu_id": "p2", "ip_addr": ""},
        ]
        self.update_request = wrapper.UpdateRequest(
            ecu=[
                {"ecu_id": "autoware"},
                {"ecu_id": "p1"},
                {"ecu_id": "p2"},
            ]
        )

    @pytest.fixture(autouse=True)
    def mock_setup(self, mocker: pytest_mock.MockerFixture, setup_ecus, setup_executor):
        from app.ecu_info import EcuInfo
        from app.ota_client import OTAClient, OTAUpdateFSM
        from app.ota_client_call import OtaClientCall

        ###### mock otaclient_call ######
        self._ota_client_call = typing.cast(
            OtaClientCall, mocker.MagicMock(spec=OtaClientCall)
        )
        self._ota_client_call.status_call = mocker.MagicMock(
            wraps=self._subecs.get_status
        )
        self._ota_client_call.update_call = mocker.MagicMock(
            wraps=self._subecs.start_update
        )

        ###### mock otaupdate_fsm ######
        _wait_for_update_finished = asyncio.Event()

        def _all_update_finished():
            logger.info("all update finished!")
            _wait_for_update_finished.set()

        _ota_update_fsm = typing.cast(OTAUpdateFSM, mocker.MagicMock(spec=OTAUpdateFSM))
        _ota_update_fsm.stub_cleanup_finished.side_effect = _all_update_finished
        _ota_update_fsm.stub_wait_for_local_update.return_value = True
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.OTAUpdateFSM",
            return_value=_ota_update_fsm,
        )
        self._fsm = _ota_update_fsm
        self._wait_for_update_finished = _wait_for_update_finished

        ###### mock ecu_info ######
        _ecu_info_mock = typing.cast(EcuInfo, mocker.MagicMock(spec=EcuInfo))
        _ecu_info_mock.get_ecu_id.return_value = self._my_ecuid
        _ecu_info_mock.get_available_ecu_ids.return_value = list(
            self._subecu_dict.keys()
        ) + [self._my_ecuid]
        _ecu_info_mock.get_secondary_ecus.return_value = self._subecu_list_ecu_info

        ###### mock otaclient ######
        self._ota_client_mock = typing.cast(OTAClient, mocker.MagicMock())
        self._ota_client_mock.live_ota_status.request_update.return_value = True

        def _received_local_update(*args, **kwargs):
            logger.info("my ecu received update request!")

        self._ota_client_mock.update.side_effect = _received_local_update

        ###### patch ######
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.EcuInfo", return_value=_ecu_info_mock
        )
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.OTAClient",
            return_value=self._ota_client_mock,
        )
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.proxy_cfg.enable_local_ota_proxy", False
        )
        mocker.patch(
            f"{cfg.OTACLIENT_STUB_MODULE_PATH}.OtaClientCall", self._ota_client_call
        )

    async def test_update(self):
        from app.ota_client_stub import OtaClientStub

        _ota_client_stub = OtaClientStub()
        # TODO: inspect response
        await _ota_client_stub.update(self.update_request)

        # wait for update finished
        await self._wait_for_update_finished.wait()

        # assert ota updates for subecus are dispatched
        assert self._subecs.if_all_subecus_received_update()
        # assert local update is dispatched
        self._ota_client_mock.update.assert_called_once()
        # assert update finished
        self._fsm.stub_cleanup_finished.assert_called_once()