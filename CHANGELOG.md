# Changelog

## [3.8.0-rc0+20240513](https://github.com/Bodong-Yang/ota-client/compare/v3.7.1-rc0+20240513...v3.8.0-rc0+20240513) (2024-10-15)


### Features

* add jetson-uefi boot control support, refine jetson-cboot boot control implementation ([#300](https://github.com/Bodong-Yang/ota-client/issues/300)) ([855ec23](https://github.com/Bodong-Yang/ota-client/commit/855ec231c4dc263081137cbeace72883790f7cbe))
* introduce firmware package control for NVIDIA Jetson device ([#376](https://github.com/Bodong-Yang/ota-client/issues/376)) ([e60c0d1](https://github.com/Bodong-Yang/ota-client/commit/e60c0d1bd163dcf1d55d51516442bb2873748b6a))


### Bug Fixes

* **boot_control:** jetson_common, grub: support detecting and update rootfs indicating string that use device path  ([#393](https://github.com/Bodong-Yang/ota-client/issues/393)) ([8ae1ca8](https://github.com/Bodong-Yang/ota-client/commit/8ae1ca8d8d4042fba361240866b6167acbdd9607))
* fix jetson-cboot for BSP &lt;= r32.5.x ([#388](https://github.com/Bodong-Yang/ota-client/issues/388)) ([5291c29](https://github.com/Bodong-Yang/ota-client/commit/5291c29905aa5ff39a631f87ebbfcf78b7069c98))
* **jetson-cboot:** save firmware version file to standby slot ([#303](https://github.com/Bodong-Yang/ota-client/issues/303)) ([3c5fea7](https://github.com/Bodong-Yang/ota-client/commit/3c5fea742ea2a40a93f0cdcaf8e3caa51dbc99cb))
* proxy_info: allow to set string value to local_ota_proxy_listen_port field ([#326](https://github.com/Bodong-Yang/ota-client/issues/326)) ([0f9856d](https://github.com/Bodong-Yang/ota-client/commit/0f9856dc6c5b95e4e2ba130ede97c4c782b0b275))
* retry_task_map: fix mem leak when network is totally cut off ([#395](https://github.com/Bodong-Yang/ota-client/issues/395)) ([24b7a06](https://github.com/Bodong-Yang/ota-client/commit/24b7a0694436c5c32d758ca8b28f7551b31dee16))
