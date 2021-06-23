#!/usr/bin/env python3

import tempfile
import re
import os
import shlex
import shutil
import subprocess
from bank import BankInfo

from logging import getLogger, INFO, DEBUG

logger = getLogger(__name__)
logger.setLevel(INFO)

def make_grub_configuration_file(output_file):
    """
    make the "grub.cfg" file
    """
    command_line = "grub-mkconfig"

    try:
        with tempfile.NamedTemporaryFile(delete=False) as ftmp:
            tmp_file = ftmp.name
            with open(tmp_file, mode="w") as f:
                logger.debug(f"tmp file opened!: {ftmp.name}")
                res = subprocess.check_call(shlex.split(command_line), stdout=f)
            # move temp to grub.cfg
            if os.path.exists(output_file):
                if os.path.exists(output_file + ".old"):
                    os.remove(output_file + ".old")
                shutil.copy2(output_file, output_file + ".old")
            shutil.move(tmp_file, output_file)
    except:
        logger.exception("failed genetrating grub.cfg")
        return False
    return True

class GrubCtl:
    """
    OTA GRUB control class
    """

    def __init__(
        self,
        default_grub_file="/etc/default/grub",
        grub_config_file="/boot/grub/grub.cfg",
        custom_config_file="/boot/grub/custom.cfg",
        bank_info_file="/boot/ota/bankinfo.yaml",
        fstab_file="/etc/fstab",
    ):
        """"""
        self._bank_info = BankInfo(bank_info_file=bank_info_file, fstab_file=fstab_file)
        self._grub_cfg_file = grub_config_file
        self._custom_cfg_file = custom_config_file
        self._default_grub_file = default_grub_file

    def get_bank_info(self):
        return self._bank_info

    def _replace_linux(self, line, vmlinuz):
        # get bank info
        current_bank = self._bank_info.get_current_bank()
        current_bank_uuid = self._bank_info.get_current_bank_uuid()
        next_bank = self._bank_info.get_next_bank()
        next_bank_uuid = self._bank_info.get_next_bank_uuid()

        match = re.match(r"(\s*linux\s+)(\S*)(\s+root=)(\S*)(.*)", line)
        if match is None:
            return None
        logger.debug(f"ORG: {line}")
        while True:
            boot_device = match.group(4)
            # 1. UUID with current_bank_uuid
            if boot_device.find(f"UUID={current_bank_uuid}") >= 0:
                boot_device = boot_device.replace(current_bank_uuid, next_bank_uuid)
                break

            # 2. UUID with next_bank_uuid
            if boot_device.find(f"UUID={next_bank_uuid}") >= 0:
                logger.debug("No replace!")
                break

            # 3. device name with current_bank
            if boot_device.find(current_bank) >= 0:
                boot_device = boot_device.replace(current_bank, next_bank)
                logger.debug(f"RPL: {dev_rep}")
                logger.debug(f"current: {current_bank}")
                logger.debug(f"next: {next_bank}")
                break

            # 4. device name with next_bank
            if boot_device.find(next_bank) >= 0:
                logger.debug("No replace!")
                break

            # 5. error
            raise Exception(f"root partition missmatch! {line}")

        label = match.group(1)
        image = match.group(2) if vmlinuz is None else f"/{os.path.basename(vmlinuz)}"
        root = match.group(3)
        params = match.group(5)
        return f"{label}{image}{root}{boot_device}{params}\n"

    def _replace_initrd(self, line, initrd):
        match = re.match(r"(\s*initrd\s+)(\S*)(.*)", line)
        if match is None:
            return None
        label = match.group(1)
        image = match.group(2) if initrd is None else f"/{os.path.basename(initrd)}"
        params = match.group(3)
        return f"{label}{image}{params}\n"

    def change_to_next_bank(self, config_file, vmlinuz, initrd):
        """
        change the custum configuration menu root partition device
        """
        if not os.path.exists(config_file):
            logger.warning(f"File not exist: {config_file}")
            return False
        logger.debug("geberate temp file!")
        with tempfile.NamedTemporaryFile(delete=False) as ftmp:
            tmp_file = ftmp.name
            logger.debug(f"temp file: {ftmp.name}")
            with open(tmp_file, mode="w") as f:
                logger.debug("temp file open!")
                with open(config_file, mode="r") as fcustom:
                    logger.debug(f"custum config file open: {config_file}")
                    # read lines from custum config file
                    lines = fcustom.readlines()
                    for l in lines:
                        try:
                            # `linux`
                            line = self._replace_linux(l, vmlinuz)
                            if line is not None:
                                f.write(line)
                                continue

                            # `initrd`
                            line = self._replace_initrd(l, initrd)
                            if line is not None:
                                f.write(line)
                                continue

                            f.write(l)
                        except Exception as e:
                            logger.exception("_replace_linux")
                            return False

                    f.flush()
        if os.path.exists(config_file):
            # backup
            shutil.copy(config_file, config_file + ".old")
        # mv tmp file to custom config file
        shutil.move(tmp_file, config_file)
        return True

    def make_grub_custom_configuration_file(
        self, input_file, output_file, vmlinuz, initrd
    ):
        """
        generate the custom configuration file for the another bank boot.
        """
        # input_file = self._grub_cfg_file
        logger.debug(f"input_file: {input_file}")
        logger.debug(f"output_file: {output_file}")

        if not os.path.exists(input_file):
            logger.info(f"No input file: {input_file}")
            return

        # output_file = self._custom_cfg_file

        banka_uuid = self._bank_info.get_banka_uuid()
        bankb_uuid = self._bank_info.get_bankb_uuid()

        menuentry_start = "menuentry "
        menuentry_end = "}"

        linux_root_re = r"linux.+root="
        root_device_uuid_str = "root=UUID=" + self._bank_info.get_current_bank_uuid()
        root_device_str = "root=" + self._bank_info.get_current_bank()

        found_target = False
        with tempfile.NamedTemporaryFile(delete=False) as ftmp:
            tmp_file = ftmp.name
            logger.debug(f"tmp file: {ftmp.name}")
            with open(ftmp.name, mode="w") as fout:
                with open(input_file, mode="r") as fin:
                    logger.debug(f"{input_file} opened!")
                    menu_writing = False
                    lines = fin.readlines()
                    for l in lines:
                        if menu_writing:
                            fout.write(l)
                            # check menuentry end
                            if 0 <= l.find(menuentry_end):
                                logger.debug("menu writing end!")
                                menu_writing = False
                                break
                            match = re.search(linux_root_re, l)
                            if match:
                                logger.debug(f"linux root match: {l}")
                                # check root
                                logger.debug(f"root uuid: {root_device_uuid_str}")
                                logger.debug(f"root devf: {root_device_str}")
                                if l.find(root_device_uuid_str) >= 0:
                                    logger.debug(f"found target: {l}")
                                    found_target = True
                                elif l.find(root_device_str) >= 0:
                                    logger.debug(f"found target: {l}")
                                    found_target = True
                        else:
                            # check menuentry start
                            if found_target:
                                break
                            if 0 == l.find(menuentry_start):
                                logger.debug(f"menuentry found! : {l}")
                                menu_writing = True
                                fout.write(l)

        if not found_target:
            logger.error("No menu entry found!")
            return False
        try:
            # change root partition
            self.change_to_next_bank(tmp_file, vmlinuz, initrd)
        except Exception as e:
            logger.exception("Change next bank error:")
            return False

        if os.path.exists(output_file):
            # backup
            shutil.copy(output_file, output_file + ".old")
        # mv tmp file to custom config file
        shutil.move(tmp_file, output_file)
        return True

    @staticmethod
    def _replace_or_append(infile, outfile, replace_list):
        """
        replaces infile with replace_list and outputs to outfile.
        if replace entry is not found in infile, the entry is appended.
        """
        lines = infile.readlines()
        index_found = [False for i in replace_list]

        """ replace """
        for l in lines:

            def match_string(line, replace_list):
                for index, replace in enumerate(replace_list):
                    match = re.match(f"^({replace['search']})", l)
                    if match is not None:
                        return index
                return None

            i = match_string(l, replace_list)
            if i is not None:
                outfile.write(
                    f"{replace_list[i]['search']}{replace_list[i]['replace']}\n"
                )
                index_found[i] = True
            else:
                outfile.write(l)

        """ append """
        for i in range(len(index_found)):
            if index_found[i] == False:
                outfile.write(
                    f"{replace_list[i]['search']}{replace_list[i]['replace']}\n"
                )

    def grub_configuration(self, style_str="menu", timeout=10):
        """
        Grub configuration setup:
            GRUB_TIMEOUT_STYLE=menu
            GRUB_TIMEOUT=10
            GRUB_DISABLE_SUBMENU=y
        """
        replace_list = [
            {"search": "GRUB_TIMEOUT_STYLE=", "replace": "menu"},
            {"search": "GRUB_TIMEOUT=", "replace": "10"},
            {"search": "GRUB_DISABLE_SUBMENU=", "replace": "y"},
        ]

        with tempfile.NamedTemporaryFile(delete=False) as ftmp:
            temp_file = ftmp.name
            logger.debug(f"tem file: {ftmp.name}")

            with open(ftmp.name, mode="w") as f:
                with open(self._default_grub_file, mode="r") as fgrub:
                    GrubCtl._replace_or_append(fgrub, f, replace_list)
                    f.flush()

            # move temp to grub
            os.sync()
            if os.path.exists(self._default_grub_file):
                if os.path.exists(self._default_grub_file + ".old"):
                    os.remove(self._default_grub_file + ".old")
                shutil.copy2(self._default_grub_file, self._default_grub_file + ".old")
            shutil.move(temp_file, self._default_grub_file)
        return True


    def re_generate_grub_config(self):
        """
        regenarate the grub config file
        """
        # change the grub genaration configuration
        self.grub_configuration()

        # make the grub configuration file
        res = make_grub_configuration_file(self._grub_cfg_file)
        return res

    def count_grub_menue_entries_wo_submenu(self, input_file):
        """
        count the grub menu entries without submenue
        """
        menuentry_str = "menuentry "
        submenu_str = "submenu "
        menu_entries = 0

        if os.path.exists(input_file):
            with open(input_file, "r") as f:
                lines = f.readlines()
                for l in lines:
                    pos = l.find(menuentry_str)
                    if pos == 0:
                        logger.debug(f"{menu_entries} : {l}")
                        menu_entries += 1
                    pos = l.find(submenu_str)
                    if pos == 0:
                        logger.debug(f"{menu_entries} : {l}")
                        menu_entries += 1
        else:
            logger.warning(f"file not exist : {input_file}")
            menu_entries = -1
        logger.debug(f"entries: {menu_entries}")
        return menu_entries

    def count_grub_menue_entries(self, input_file):
        """
        count the grub menu entries
        """
        menuentry_str = "menuentry "
        menu_entries = 0

        if os.path.exists(input_file):
            with open(input_file, "r") as f:
                lines = f.readlines()
                for l in lines:
                    pos = l.find(menuentry_str)
                    if pos >= 0:
                        logger.debug(f"{menu_entries} : {l}")
                        menu_entries += 1
        else:
            logger.warning(f"file not exist! : {input_file}")
            menu_entries = -1

        logger.debug(f"entries: {menu_entries}")
        return menu_entries

    def set_next_boot_entry(self, menuentry_no):
        """
        set next boot grub menue entry to custom config menu
        """
        command_line = "grub-reboot " + str(menuentry_no)
        try:
            logger.debug(f"Do: subproxess.check_call({command_line})")
            res = subprocess.check_call(shlex.split(command_line))
        except:
            logger.exception("grub-setreboot error!")
            return False
        return True

    def set_next_bank_boot(self, no_submenu=True):
        """
        set next boot grub menue entry to custom config menu
        """
        # get grub.cfg menuentries
        if no_submenu:
            menu_entries = self.count_grub_menue_entries_wo_submenu(self._grub_cfg_file)
        else:
            menu_entries = self.count_grub_menue_entries(self._grub_cfg_file)
        if menu_entries > 0:
            # set next boot menuentry to custum menuentry
            res = self.set_next_boot_entry(menu_entries)
        else:
            logger.error("No grub entry in the grub.cfg file!")
            return False
        return res

    @staticmethod
    def delete_custom_cfg_file():
        """
        delete custom.cfg file
        """
        target_file = "/boot/grub/custom.cfg"
        os.remove(target_file)

    @staticmethod
    def reboot():
        """
        reboot
        """
        command_line = "reboot"
        try:
            res = subprocess.check_call(shlex.split(command_line))
        except:
            logger.exception("reboot error!")
            return False
        return True

    def prepare_grub_switching_reboot(self, vmlinuz, initrd):
        """
        prepare for GRUB control reboot for switching to another bank
        """
        # make custum.cfg file
        res = self.make_grub_custom_configuration_file(
            self._grub_cfg_file, self._custom_cfg_file, vmlinuz, initrd
        )

        if res:
            # set next boot menu
            res = self.set_next_bank_boot()
        else:
            return False
        return res

    def grub_rollback_prepare(self):
        """
        GRUB data backup for rollback

        """
        # copy for rollback
        if os.path.exists(self._grub_cfg_file):
            shutil.copy2(self._grub_cfg_file, self._grub_cfg_file + ".rollback")
        else:
            logger.error("grub configuratiuion file not exist!")
            return False
        return True

    def grub_rollback_reboot(self):
        """
        GRUB rollback reboot
        """
        # ToDo: implement
        return True
