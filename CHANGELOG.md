# Changelog

## 3.7.1 (2024-05-07)


### Features

* add release action to release .whl ([#177](https://github.com/Bodong-Yang/ota-client/issues/177)) ([61cc7b1](https://github.com/Bodong-Yang/ota-client/commit/61cc7b1195330ef6caeda93c309ca3f7ead85cb8))
* support firmware ([#204](https://github.com/Bodong-Yang/ota-client/issues/204)) ([f59cb26](https://github.com/Bodong-Yang/ota-client/commit/f59cb26651f85a6519e1ba50e910fd1e2900d002))
* **v3.7.x:** bootcontrol: refactor jetson-cboot, add new firmware update support ([#287](https://github.com/Bodong-Yang/ota-client/issues/287)) ([794770c](https://github.com/Bodong-Yang/ota-client/commit/794770c63114aca316813c663bdacd4783cbc60f))


### Bug Fixes

* enable put ota_proxy log to cloud ([#179](https://github.com/Bodong-Yang/ota-client/issues/179)) ([f57a631](https://github.com/Bodong-Yang/ota-client/commit/f57a631052bc74cb36370f9a9a6aa3e80f7bfd4e))
* fix proto version ([#209](https://github.com/Bodong-Yang/ota-client/issues/209)) ([04e43ea](https://github.com/Bodong-Yang/ota-client/commit/04e43eaa0f080b2e688270a48e66d8ef25c8d5ff))
* illegal param ([#123](https://github.com/Bodong-Yang/ota-client/issues/123)) ([d6bf3a0](https://github.com/Bodong-Yang/ota-client/commit/d6bf3a02b44b0753b19c9f7819ad5fed66b981af))
* log_setting: add special treatment for not-a-URL being passed in ([fe9322f](https://github.com/Bodong-Yang/ota-client/commit/fe9322f89357ebb08ba8fa5e9ac62a0f111b0075))
* log-group for ota-proxy ([#189](https://github.com/Bodong-Yang/ota-client/issues/189)) ([94fcb37](https://github.com/Bodong-Yang/ota-client/commit/94fcb373ac484569b92f95d4626a59fb2d10ab1a))
* persists file handling should be at PROCESS_POSTUPDATE phase ([#274](https://github.com/Bodong-Yang/ota-client/issues/274)) ([1aa06ed](https://github.com/Bodong-Yang/ota-client/commit/1aa06ed602787d74ba8b587aa7a3ec42188421d7))
* properly handling swapfile during persist file handling ([#275](https://github.com/Bodong-Yang/ota-client/issues/275)) ([dfd1237](https://github.com/Bodong-Yang/ota-client/commit/dfd12378d94afd59e15a951e4caf20c8e4e77f99))
* python path to use venv ([#173](https://github.com/Bodong-Yang/ota-client/issues/173)) ([5b202e8](https://github.com/Bodong-Yang/ota-client/commit/5b202e8f02ebfbded5834b1d8c5e9ee84e64c978))
* status phase mapping ([#210](https://github.com/Bodong-Yang/ota-client/issues/210)) ([427efc3](https://github.com/Bodong-Yang/ota-client/commit/427efc36b6d3413ad56afb803eea82564b003558))
* systemd restart ([#199](https://github.com/Bodong-Yang/ota-client/issues/199)) ([a0bfb38](https://github.com/Bodong-Yang/ota-client/commit/a0bfb3805138401a21aea4c1ae340cb986fa1dee))
* use cp -T not to create {nvme}/boot/boot directory ([#119](https://github.com/Bodong-Yang/ota-client/issues/119)) ([d87b165](https://github.com/Bodong-Yang/ota-client/commit/d87b16522d973b36b045e1774770e5302752e4db))
* **v3.6.x:** fix and refine logs uploading ([#280](https://github.com/Bodong-Yang/ota-client/issues/280)) ([bc83e31](https://github.com/Bodong-Yang/ota-client/commit/bc83e31518635acdd087890e7d33d60c44c449e5))
* **v3.6.x:** otaclient.persist_file_handling: fix incorrect new swapfile fpath ([#281](https://github.com/Bodong-Yang/ota-client/issues/281)) ([1422677](https://github.com/Bodong-Yang/ota-client/commit/14226773f895521245e8e96605cf1b83aac02274))
* **v3.7.x:** not merging available_ecu_ids from child ECUs status resp again ([#290](https://github.com/Bodong-Yang/ota-client/issues/290)) ([f73c6d0](https://github.com/Bodong-Yang/ota-client/commit/f73c6d0102e5098a6f07aacfa975fa9785ab28fe))


### Miscellaneous Chores

* **tags:** release 3.7.1 ([c091428](https://github.com/Bodong-Yang/ota-client/commit/c0914285e362faf6451e255e8823c7cd41313eed))
