# Offline OTA image builder

`tools.offline_ota_image_builder` is a helper package for bundling offline OTA image from the OTA images build by ota-metadata(or images compatible with OTA image specification).
Built image can be used as external cache source for otaproxy, or used by full offline OTA helper util to trigger fully offline OTA update.

**NOTE**: full offline OTA helper util is not yet implemented.

It provides the following features:

1. build offline OTA image from the OTA images built by ota-metadata(or images compatible with OTA image specification),
2. export built offline OTA image as tar archive,
3. prepare and export built image onto specific block device as external cache source device for otaproxy.

<!--- Please check documentation at [OTA cache mechanism design for otaproxy](https://tier4.atlassian.net/l/cp/yzmnPx9T) for more details. -->

## Expected image layout for input OTA images

This package currently only recognizes the OTA images generated by [ota-metadata@a711013](https://github.com/tier4/ota-metadata/commit/a711013), or the image layout compatible with the ota-metadata and OTA image layout specification as follow.

```text
Example OTA image layout:
.
├── data
│   ├── <...files with full paths...>
│   └── ...
├── data.zst
│   ├── <... compressed OTA file ...>
│   └── <... naming: <file_sha256>.zst ...>
├── certificate.pem
├── dirs.txt
├── metadata.jwt
├── persistents.txt
├── regulars.txt
└── symlinks.txt
```

Please also refere to [ota-metadata](https://github.com/tier4/ota-metadata) repo for the implementation of OTA image layout specification.

## Offline OTA image layout

The rootfs of the built image has the following layout:

```text
.
├── manifest.json
├── data
│   ├── <OTA_file_sha256hash> # uncompressed file
│   ├── <OTA_file_sha256hash>.zst # zst compressed file
│   └── ...
└── meta
    ├── <idx> # corresponding to the order in manifest.image_meta
    │   └── <list of OTA metafiles...>
    └── ...
        └── <list of OTA metafiles...>

```

This layout is compatible with external cache source's layout, which means any offline OTA image can natually directly be used as external cache source recognized by otaproxy(but user still needs to prepare the device either by themselves and extract the offline OTA image rootfs onto the prepared device, or prepare the device with this **offline_ota_image_builder** package).

<!--- Please check [External cache source](https://tier4.atlassian.net/wiki/spaces/WEB/pages/2813984854/OTA+cache+mechanism+design+for+otaproxy#External-cache-source) section of the doc for more details. --->

## Offline OTA image Manifest schema

Offline OTA image's rootfs contains a `manifest.json` file with a single JSON object in it. This file includes the information related to this offline OTA image, including the bundled OTA images' metadata.

```json
{
  "schema_version": 1,
  "image_layout_version": 1,
  "build_timestamp": 1693291679,
  "data_size": 1122334455,
  "data_files_num": 12345,
  "meta_size": 112233,
  "image_meta": [
    {
      "ecu_id": "<ecu_id>",
      "image_version": "<image_version>",
      "ota_metadata_version": 1,
    },
    ...
  ],
}
```

<!--- Please check [Build external cache source](https://tier4.atlassian.net/wiki/spaces/WEB/pages/2813984854/OTA+cache+mechanism+design+for+otaproxy#Build-external-cache-source) section for more details. --->

## How to use

### Prepare the dependencies

This image builder requires latest ota-client to be installed/accessable. The recommended way to install dependencies is to init a virtual environment and install the ota-client into this venv, and then execute the image_builder with this venv.

1. git clone the latest ota-client repository:

    ```bash
    $ git clone https://github.com/tier4/ota-client.git
    # image builder is located at ota-client/tools/offline_ota_image_builder
    ```

2. prepare the virtual environment and activate it:

    ```bash
    $ python3 -m venv venv
    $ . venv/bin/active
    (venv) $
    ```

3. install the ota-client into the virtual environment:

    ```bash
    (venv) $ pip install ota-client
    ```

### Build image and export

#### Builder usage

```text
usage: offline_ota_image_builder [-h] --image <ECU_NAME>:<IMAGE_PATH>[:<IMAGE_VERSION>]
                                 [-o <OUTPUT_PATH>] [-w <DEVICE>] [--confirm-write-to]

Helper script that builds offline OTA image with given OTA image(s) as external cache source or for
offline OTA use.

options:
  -h, --help            show this help message and exit
  --image <ECU_NAME>:<IMAGE_PATH>[:<IMAGE_VERSION>]
                        OTA image for <ECU_ID> as tar archive(compressed or uncompressed), this
                        option can be used multiple times to include multiple images.
  -o <OUTPUT_PATH>, --output <OUTPUT_PATH>
                        save the generated image rootfs into tar archive to <OUTPUT_PATH>.
  -w <DEVICE>, --write-to <DEVICE>
                        write the image to <DEVICE> and prepare the device as external cache source
                        device.
  --force-write-to    prepare <DEVICE> as external cache source device without inter-active confirmation,
                      only valid when used with -w option.
```

Execute the image builder by directly calling it from the source code. This package requires `root` permission to run(required by extracting OTA image and preparing external cache source device).

Option `--image <ECU_NAME>:<IMAGE_PATH>[:<IMAGE_VERSION>]` is used to specify OTA image to be included. This option can be used multiple times to specify multiple OTA images.

Option `--write-to <DEVICE>` is used to prepare external cache source device used by otaproxy. The specified device will be formatted as `ext4`, fslabel with `ota_cache_src`, and be exported with the built offline OTA image's rootfs. If this package is used in a non-interactive script, option `--force-write-to` can be used to bypass interactive confirmation.

Option `--output <OUTPUT>` specify where to save the exported tar archive of built image.

User must at least specifies one of `--write-to` and `--output`, or specifies them together.

#### Usage 1: Build offline OTA image and export it as tar archive

```bash
# current folder layout: venv ota-client
(venv) $ cd ota-client
(venv) $ sudo -E env PATH=$PATH python3 -m tools.offline_ota_image_builder --image=p1:p1_image.tgz:ver_20230808 --image=p2:p2_image.tgz:ver_20230808 --output=t2.tar
```

This will build the offline OTA image with `p1_image.tgz` and `p2_image.tgz`, which are for ECU `p1` and `p2`, and export the built image as `t2.tar` tar archive.

### Usage 2: Build the offline OTA image and create external cache source dev

```bash
# current folder layout: venv ota-client
(venv) $ cd ota-client
(venv) $ sudo -E env PATH=$PATH python3 -m tools.offline_ota_image_builder --image=p1:p1_image.tgz:ver_20230808 --image=p2:p2_image.tgz:ver_20230808 --write-to=/dev/<target_dev>
```

This will build the offline OTA image with `p1_image.tgz` and `p2_image.tgz`, which are for ECU `p1` and `p2`, and then prepare the `/dev/<target_dev>` as external cache source device(ext4 filesystem labelled with `ota_cache_src`) with image rootfs exported to the filesystem on `/dev/<target_device>`.

### Usage 3: Build the offline OTA image, export it as tar archive and prepare external cache source dev

```bash
# current folder layout: venv ota-client
(venv) $ cd ota-client
(venv) $ sudo -E env PATH=$PATH python3 -m tools.offline_ota_image_builder --image=p1:p1_image.tgz:ver_20230808 --image=p2:p2_image.tgz:ver_20230808 --output=t2.tar --write-to=/dev/<target_dev>
```
