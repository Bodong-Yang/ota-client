#!/usr/bin/env python3

import tempfile
import os
import shlex
import shutil
import subprocess
import getpass
import yaml


class BankInfo:
    """
    OTA Bank device info class
    """

    def __init__(
        self, bank_info_file="/boot/ota/bankinfo.yaml", fstab_file="/etc/fstab"
    ):
        """
        Initialize
        """
        self.__verbose = False
        #
        self._bank_info_file = bank_info_file
        self._fstab_file = fstab_file
        # bank A bank B info
        if not os.path.exists(self._bank_info_file):
            self._gen_bankinfo_file(self._fstab_file)
        self._banka, self._bankb = self._get_bank_info(bank_info_file)
        self._banka_uuid = self._get_uuid_from_blkid(self._banka)
        self._bankb_uuid = self._get_uuid_from_blkid(self._bankb)
        # current bank info
        self._current_bank = ""
        self._current_bank_uuid_str = ""
        # next bank info
        self._next_bank = ""
        self._next_bank_uuid_str = ""
        self._read_fail = False
        res = self._setup_current_next_root_dev(fstab_file)

    def _blkid(self):
        """
        cleanup next bank
        """
        try:
            command_line = "blkid"
            if self.__verbose:
                print("commandline: ", command_line)
            blk_info = subprocess.check_output(shlex.split(command_line))
            blks_byte = blk_info.split(b"\n")
            blks = []
            for blk in blks_byte:
                blk_dict = {
                    "DEV": "",
                    "LABEL": "",
                    "UUID": "",
                    "TYPE": "",
                    "PARTLABEL": "",
                }
                for info in blk.decode().split():
                    if info[-1] == ":":
                        blk_dict["DEV"] = info[:-1]
                    elif info.find("LABEL=") == 0:
                        blk_dict["LABEL"] = info[7:-1]
                    elif info.find("UUID=") == 0:
                        blk_dict["UUID"] = info[6:-1]
                    elif info.find("TYPE=") == 0:
                        blk_dict["TYPE"] = info[6:-1]
                    elif info.find("PARTLABEL=") == 0:
                        blk_dict["PARTLABEL"] = info[11:-1]
                blks.append(blk_dict)
            if self.__verbose:
                for info in blks:
                    print(info)
        except Exception as e:
            print("execution error!:", e)
            return []
        return blks

    def _get_ext4_blks_by_blkid(self):
        """"""
        ext4_blks = []
        blks = self._blkid()
        # dev_info = getdevinfo.getdevinfo.get_info()
        if blks == []:
            if self.__verbose:
                print("Cannot get block info!")
        else:
            for info in blks:
                if info["TYPE"] == "ext4":
                    ext4_blks.append(info)
        return ext4_blks

    def _get_devfile(self, fstab_dev):
        if fstab_dev.find("UUID=") == 0:
            # UUID
            uuid = fstab_dev[5:]
            uuid_dev = "/dev/disk/by-uuid/" + uuid
            if os.path.exists(uuid_dev):
                devfile = os.path.realpath(uuid_dev)
                return devfile, uuid
            else:
                if self.__verbose:
                    print("No uuid device: ", uuid_dev)
                return "", ""
        elif fstab_dev.find("/dev/disk/by-uuid/") == 0:
            # uuid devicefile
            uuid = fstab_dev[18:]
            uuid_dev = fstab_dev
            if os.path.exists(uuid_dev):
                devfile = os.path.realpath(uuid_dev)
                return devfile, uuid
            else:
                if self.__verbose:
                    print("No uuid device: ", uuid_dev)
                return "", ""
        elif fstab_dev.find("/dev/") == 0:
            # devfile
            return fstab_dev, ""
        else:
            if self.__verbose:
                print("device is not UUID or devfile: ", fstab_dev)
        return "", ""

    def _get_current_devfile_by_fstab(self, fstab_file):
        """"""
        if not os.path.isfile(fstab_file):
            if self.__verbose:
                print("file not exist: ", fstab_file)
            return "", "", "", ""
        with open(fstab_file, "r") as f:
            lines = f.readlines()
            root_devfile = ""
            root_uuid = ""
            boot_devfile = ""
            boot_uuid = ""
            for l in lines:
                if l[0] == "#":
                    continue
                fstab_list = l.split()
                if fstab_list[1] == "/":
                    root_devfile, root_uuid = self._get_devfile(fstab_list[0])
                elif fstab_list[1] == "/boot":
                    boot_devfile, boot_uuid = self._get_devfile(fstab_list[0])
                else:
                    if self.__verbose:
                        print("others: ", fstab_list)
        return root_devfile, root_uuid, boot_devfile, boot_uuid

    def _gen_bankinfo_file(self, fstab_file):
        """
        generate the bank information file
        """
        (
            root_devfile,
            root_uuid,
            boot_devfile,
            boot_uuid,
        ) = self._get_current_devfile_by_fstab(fstab_file)
        blks = self._get_ext4_blks_by_blkid()
        stby_devfile = ""
        for blk in blks:
            if blk["TYPE"] == "ext4":
                if blk["DEV"] == root_devfile or blk["UUID"] == root_uuid:
                    print("root dev: ", root_devfile, root_uuid)
                elif blk["DEV"] == boot_devfile or blk["UUID"] == boot_uuid:
                    print("boot dev: ", boot_devfile, boot_uuid)
                else:
                    print("another bank: ", blk)
                    stby_devfile = blk["DEV"]
                    stby_uuid = blk["UUID"]
                    break
            else:
                if self.verbose:
                    print("no ext4: ", blk)
        if boot_devfile == "" or root_devfile == "" or stby_devfile == "":
            print("device info error!")
            print(
                "root: "
                + root_devfile
                + " boot: "
                + boot_devfile
                + " stby: "
                + stby_devfile
            )
            return False
        else:
            with tempfile.NamedTemporaryFile(delete=False) as ftmp:
                tmp_file = ftmp.name
                with open(ftmp.name, "w") as f:
                    f.write("banka: " + root_devfile + "\n")
                    f.write("bankb: " + stby_devfile + "\n")
                    if self.__verbose:
                        print("banka: " + root_devfile)
                        print("bankb: " + stby_devfile)
                    f.flush()
            os.sync()
            dir_name = os.path.dirname(self._bank_info_file)
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            shutil.move(tmp_file, self._bank_info_file)
            os.sync()
        return True

    def _get_bank_info(self, ota_config_file):
        """
        get bank information
        """
        banka = ""
        bankb = ""
        try:
            with open(ota_config_file, "r") as fyml:
                if self.__verbose:
                    print("open: " + ota_config_file)
                ota_config = yaml.load(fyml, Loader=yaml.SafeLoader)
                banka = ota_config["banka"]
                bankb = ota_config["bankb"]
                if self.__verbose:
                    print("banka: " + banka + " bankb: " + bankb)
        except:
            print("Cannot get bank infomation!:", ota_config_file)
        return banka, bankb

    def _setup_current_next_root_dev(self, fstab_file):
        """
        setup the current/next root device from '/etc/fstab'
        """
        with open(fstab_file, "r") as f:
            lines = f.readlines()

        for l in lines:
            if l[0] == "#":
                continue

            fstab_list = l.split()
            if fstab_list[1] == "/":
                # root mount line
                if self.__verbose:
                    print("root found: " + fstab_list[0])
                if fstab_list[0].find("UUID=") == 0:
                    # UUID type definition
                    self._current_bank_uuid_str = fstab_list[0]
                    if self._current_bank_uuid_str.find(self._banka_uuid) >= 0:
                        # current bank is A
                        self._current_bank = self._banka
                        self._next_bank = self._bankb
                        self._next_bank_uuid_str = "UUID=" + self._bankb_uuid
                    elif self._current_bank_uuid_str.find(self._bankb_uuid) >= 0:
                        # current bank is B
                        self._current_bank = self._bankb
                        self._next_bank = self._banka
                        self._next_bank_uuid_str = "UUID=" + self._banka_uuid
                    else:
                        # current bank is another bank
                        self._read_fail = True
                        print("Error : current bank is not banka or bankb!")
                elif fstab_list[0].find("/dev/disk/by-uuid/") == 0:
                    # by-uuid device file
                    self._current_bank_uuid_str = fstab_list[0]
                    if self._current_bank_uuid_str.find(self._banka_uuid) >= 0:
                        # current bank is A
                        self._current_bank = self._banka
                        self._next_bank = self._bankb
                        self._next_bank_uuid_str = (
                            "/dev/disk/by-uuid/" + self._bankb_uuid
                        )
                    elif self._current_bank_uuid_str.find(self._bankb_uuid) >= 0:
                        # current bank is B
                        self._current_bank = self._bankb
                        self._next_bank = self._banka
                        self._next_bank_uuid_str = (
                            "/dev/disk/by-uuid/" + self._banka_uuid
                        )
                    else:
                        self._read_fail = True
                        print("Error : current bank is not banka or bankb!")
                else:
                    # device file name
                    self._current_bank = fstab_list[0]
                    if self._current_bank == self._banka:
                        self._current_bank_uuid_str = "UUID=" + self._banka_uuid
                        self._next_bank = self._bankb
                        self._next_bank_uuid_str = "UUID" + self._bankb_uuid
                    elif self._current_bank == self._bankb:
                        self._current_bank_uuid_str = "UUID=" + self._bankb_uuid
                        self._next_bank = self._banka
                        self._next_bank_uuid_str = "UUID=" + self._banka_uuid
                    else:
                        self._read_fail = True
                        print("Error : current bank is not banka or bankb!")
                return fstab_list[0]

        print("root not found!")
        return ""

    def setup_next_bank_fstab(self, fstab_file=""):
        """
        setup next bank to fstab
        """
        if fstab_file == "":
            fstab_file = self._fstab_file

        # read fstab
        with open(fstab_file, "r") as f:
            lines = f.readlines()

        with tempfile.NamedTemporaryFile(delete=False) as ftmp:
            tmp_file = ftmp.name
            with open(ftmp.name, "w") as fout:
                for l in lines:
                    if l[0] == "#":
                        fout.write(l)
                        continue
                    fstab_list = l.split()
                    if fstab_list[1] == "/":
                        lnext = ""
                        if fstab_list[0].find(self._current_bank) >= 0:
                            # devf found
                            lnext = l.replace(self._current_bank, self._next_bank)
                        elif fstab_list[0].find(self.get_current_bank_uuid()) >= 0:
                            # uuid found
                            lnext = l.replace(
                                self.get_current_bank_uuid(), self.get_next_bank_uuid()
                            )
                        elif (
                            fstab_list[0].find(self._current_bank) >= 0
                            or fstab_list[0].find(self.get_next_bank_uuid()) >= 0
                        ):
                            # next bank found
                            if self.__verbose:
                                print("Already set to next bank!")
                            lnext = l
                        else:
                            raise (Exception("root device mismatch in fstab."))
                        fout.write(lnext)
                    else:
                        fout.write(l)
        # replace to new fstab file
        shutil.copy(fstab_file, fstab_file + ".old")
        shutil.move(tmp_file, fstab_file)

        return True

    def _get_uuid_from_blkid(self, bank):
        """
        get bank device uuid by the 'blkid' command
        """
        if self.__verbose:
            print("bank: " + bank)
        # passwd = (getpass.getpass() + '\n').encode()
        command_line = "sudo blkid " + bank
        if self.__verbose:
            print("command_line: " + command_line)
        out = subprocess.check_output(shlex.split(command_line))
        if self.__verbose:
            print(out.decode("utf-8"))
        blk = shlex.split(out.decode("utf-8"))
        if self.__verbose:
            print(blk)
        uuid = ""
        if len(blk) > 0:
            pos = blk[1].find("UUID=")
            if pos == 0:
                uuid = blk[1].replace("UUID=", "")
        if self.__verbose:
            print("uuid for " + bank + ": " + uuid)
        return uuid

    def get_banka(self):
        """
        Get bank A
        """
        return self._banka

    def get_banka_uuid(self):
        """
        Get bank A UUID
        """
        return self._banka_uuid

    def get_banka_uuid(self):
        """
        Get bank A UUID
        """
        return self._banka_uuid

    def is_banka(self, bank):
        """
        Is bank A
        """
        if bank == self._banka:
            return True
        return False

    def is_banka_uuid(self, bank_uuid):
        """
        Is bank A UUID
        """
        if bank_uuid == self._banka_uuid:
            return True
        return False

    def get_bankb(self):
        """
        Get bank B
        """
        return self._bankb

    def get_bankb_uuid(self):
        """
        Get bank B UUID
        """
        return self._bankb_uuid

    def get_bankb_uuid(self):
        """
        Get bank B UUID
        """
        return self._bankb_uuid

    def is_bankb(self, bank):
        """
        Is bank B
        """
        if bank == self._bankb:
            return True
        return False

    def is_bankb_uuid(self, bank_uuid):
        """
        Is bank B UUID
        """
        if bank_uuid == self._bankb_uuid:
            return True
        return False

    def get_current_bank(self):
        """
        Get current bank devoice file
        """
        # print("current_bank: " + self._current_bank)
        return self._current_bank

    def get_current_bank_uuid(self):
        """
        Get current bank UUID
        """
        if self.is_banka(self._current_bank):
            return self._banka_uuid
        elif self.is_bankb(self._current_bank):
            return self._bankb_uuid
        return ""

    def get_current_bank_uuid_str(self):
        """
        Get current bank UUID string
        """
        # print("current_bank_uuid: " + self._current_bank_uuid_str)
        return self._current_bank_uuid_str

    def is_current_bank(self, bank_str):
        """
        Confirm the current bank
        """
        #
        if bank_str != self._banka and bank_str != self._bankb:
            print("device mismatch error: " + bank_str)
            print("    banka: " + self._banka)
            print("    bankb: " + self._bankb)
            return False
        # get current root device
        if self._current_bank != self._banka_dev and self._current_bank != self._banka:
            print("current root mismatch error: " + self._current_bank)
            print("    banka: " + self._banka)
            print("    bankb: " + self._bankb)
            return False
        #
        if self._current_bank == bank_str:
            return True
        return False

    def get_next_bank(self):
        """
        Get next bank
        """
        # print("next_bank: " + self._next_bank)
        return self._next_bank

    def get_next_bank_uuid(self):
        """
        Get next bank UUID
        """
        if self.is_banka(self._next_bank):
            return self._banka_uuid
        elif self.is_bankb(self._next_bank):
            return self._bankb_uuid
        return ""

    def get_next_bank_uuid_str(self):
        """
        Get the next bank UUID string
        """
        print("next_bank_uuid: " + self._next_bank_uuid_str)
        return self._next_bank_uuid_str


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--bankinfo", help="bank info file path name", default="/boot/ota/bankinfo.yaml"
    )
    parser.add_argument("--fstab", help="fstab file path name", default="/etc/fstab")

    args = parser.parse_args()

    bank_info = BankInfo(bank_info_file=args.bankinfo, fstab_file=args.fstab)

    root_dev, root_uuid, boot_dev, boot_uuid = bank_info._get_current_devfile_by_fstab(
        "/etc/fstab"
    )
    print("root dev: ", root_dev)
    print("root uuid: ", root_uuid)
    print("boot dev: ", boot_dev)
    print("boot uuid: ", boot_uuid)

    print("bank a: ", bank_info._banka)
    print("bank a uuid:", bank_info._banka_uuid)

    print("bank b: ", bank_info._bankb)
    print("bank b uuid: ", bank_info._bankb_uuid)

    print("current bank: ", bank_info._current_bank)
    print("current bank uuid: ", bank_info._current_bank_uuid_str)

    print("next bank: ", bank_info._next_bank)
    print("next bank uuid: ", bank_info._next_bank_uuid_str)
