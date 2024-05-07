# Changelog

## [3.7.0](https://github.com/Bodong-Yang/ota-client/compare/3.6.1...v3.7.0) (2024-05-07)


### Features

* **v3.7.x:** bootcontrol: refactor jetson-cboot, add new firmware update support ([#287](https://github.com/Bodong-Yang/ota-client/issues/287)) ([794770c](https://github.com/Bodong-Yang/ota-client/commit/794770c63114aca316813c663bdacd4783cbc60f))


### Bug Fixes

* log_setting: add special treatment for not-a-URL being passed in ([fe9322f](https://github.com/Bodong-Yang/ota-client/commit/fe9322f89357ebb08ba8fa5e9ac62a0f111b0075))
* persists file handling should be at PROCESS_POSTUPDATE phase ([#274](https://github.com/Bodong-Yang/ota-client/issues/274)) ([1aa06ed](https://github.com/Bodong-Yang/ota-client/commit/1aa06ed602787d74ba8b587aa7a3ec42188421d7))
* properly handling swapfile during persist file handling ([#275](https://github.com/Bodong-Yang/ota-client/issues/275)) ([dfd1237](https://github.com/Bodong-Yang/ota-client/commit/dfd12378d94afd59e15a951e4caf20c8e4e77f99))
* **v3.6.x:** fix and refine logs uploading ([#280](https://github.com/Bodong-Yang/ota-client/issues/280)) ([bc83e31](https://github.com/Bodong-Yang/ota-client/commit/bc83e31518635acdd087890e7d33d60c44c449e5))
* **v3.6.x:** otaclient.persist_file_handling: fix incorrect new swapfile fpath ([#281](https://github.com/Bodong-Yang/ota-client/issues/281)) ([1422677](https://github.com/Bodong-Yang/ota-client/commit/14226773f895521245e8e96605cf1b83aac02274))
* **v3.7.x:** not merging available_ecu_ids from child ECUs status resp again ([#290](https://github.com/Bodong-Yang/ota-client/issues/290)) ([f73c6d0](https://github.com/Bodong-Yang/ota-client/commit/f73c6d0102e5098a6f07aacfa975fa9785ab28fe))
