import base64
from collections import defaultdict
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from OpenSSL import crypto
from pathlib import Path
from pprint import pformat
from functools import partial
from typing import (
    Any,
    ClassVar,
    DefaultDict,
    Dict,
    Iterator,
    Optional,
    Set,
    Tuple,
    Union,
)

from .configs import config as cfg
from .common import verify_file
from . import log_util

logger = log_util.get_logger(
    __name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL)
)


class OtaMetadata:
    """
    OTA Metadata Class
    """

    """
    The root and intermediate certificates exist under certs_dir.
    When A.root.pem, A.intermediate.pem, B.root.pem, and B.intermediate.pem
    exist, the groups of A* and the groups of B* are handled as a chained
    certificate.
    verify function verifies specified certificate with them.
    Certificates file name format should be: '.*\\..*.pem'
    NOTE:
    If there is no root or intermediate certificate, certification verification
    is not performed.
    """

    def __init__(self, ota_metadata_jwt):
        """
        OTA metadata parser
            url : metadata server URL
            cookie : signed cookie
            metadata_jwt : metadata JWT file name
        """
        self.__metadata_jwt = ota_metadata_jwt
        self.__metadata_dict = self._parse_metadata(ota_metadata_jwt)
        logger.info(f"metadata_dict={pformat(self.__metadata_dict)}")
        self._certs_dir = Path(cfg.CERTS_DIR)
        logger.info(f"certs_dir={self._certs_dir}")

    def verify(self, certificate: bytes):
        """"""
        # verify certificate itself before hand.
        self._verify_certificate(certificate)

        # verify metadata.jwt
        try:
            cert = crypto.load_certificate(crypto.FILETYPE_PEM, certificate)
            verify_data = self._get_header_payload().encode()
            logger.debug(f"verify data: {verify_data}")
            crypto.verify(cert, self._signature, verify_data, "sha256")
        except Exception as e:
            logger.exception("verify")
            raise ValueError(e)

    def get_directories_info(self):
        """
        return
            directory file info list: { "file": file name, "hash": file hash }
        """
        return self.__metadata_dict["directory"]

    def get_symboliclinks_info(self):
        """
        return
            symboliclink file info: { "file": file name, "hash": file hash }
        """
        return self.__metadata_dict["symboliclink"]

    def get_regulars_info(self):
        """
        return
            regular file info: { "file": file name, "hash": file hash }
        """
        return self.__metadata_dict["regular"]

    def get_persistent_info(self):
        """
        return
            persistent file info: { "file": file name, "hash": file hash }
        """
        return self.__metadata_dict["persistent"]

    def get_rootfsdir_info(self):
        """
        return
            rootfs_directory info: {"file": dir name }
        """
        return self.__metadata_dict["rootfs_directory"]

    def get_certificate_info(self):
        """
        return
            certificate file info: { "file": file name, "hash": file hash }
        """
        return self.__metadata_dict["certificate"]

    def get_total_regular_file_size(self):
        """
        return
            total regular file size: int
        """
        size = self.__metadata_dict.get("total_regular_size", {}).get("file")
        return None if size is None else int(size)

    """ private functions from here """

    def _jwt_decode(self, jwt):
        """
        JWT decode
            return payload.json
        """
        jwt_list = jwt.split(".")

        header_json = base64.urlsafe_b64decode(jwt_list[0]).decode()
        logger.debug(f"JWT header: {header_json}")
        payload_json = base64.urlsafe_b64decode(jwt_list[1]).decode()
        logger.debug(f"JWT payload: {payload_json}")
        signature = base64.urlsafe_b64decode(jwt_list[2])
        logger.debug(f"JWT signature: {signature}")

        return header_json, payload_json, signature

    def _parse_payload(self, payload_json):
        """
        Parse payload json file
        """
        keys_version = {
            "directory",
            "symboliclink",
            "regular",
            "certificate",
            "persistent",
            "rootfs_directory",
            "total_regular_size",
        }
        hash_key = "hash"
        payload = json.loads(payload_json)
        payload_dict = {
            "version": list(entry.values())[0]
            for entry in payload
            if entry.get("version")
        }

        if payload_dict["version"] != 1:
            logger.warning(f"metadata version is {payload_dict['version']}.")

        for entry in payload:
            for key in keys_version:
                if key in entry.keys():
                    payload_dict[key] = {}
                    payload_dict[key]["file"] = entry.get(key)
                    if hash_key in entry:
                        payload_dict[key][hash_key] = entry.get(hash_key)
        return payload_dict

    def _parse_metadata(self, metadata_jwt):
        """
        Parse metadata.jwt
        """
        (
            self._header_json,
            self._payload_json,
            self._signature,
        ) = self._jwt_decode(metadata_jwt)
        # parse metadata.jwt payload
        return self._parse_payload(self._payload_json)

    def _get_header_payload(self):
        """
        Get Header and Payload urlsafe base64 string
        """
        jwt_list = self.__metadata_jwt.split(".")
        return jwt_list[0] + "." + jwt_list[1]

    def _verify_certificate(self, certificate: bytes):
        ca_set_prefix = set()
        # e.g. under _certs_dir: A.1.pem, A.2.pem, B.1.pem, B.2.pem
        for cert in self._certs_dir.glob("*.*.pem"):
            if m := re.match(r"(.*)\..*.pem", cert.name):
                ca_set_prefix.add(m.group(1))
            else:
                raise ValueError("no pem file is found")
        if len(ca_set_prefix) == 0:
            logger.warning("there is no root or intermediate certificate")
            return
        logger.info(f"certs prefixes {ca_set_prefix}")

        load_pem = partial(crypto.load_certificate, crypto.FILETYPE_PEM)

        try:
            cert_to_verify = load_pem(certificate)
        except crypto.Error:
            logger.exception(f"invalid certificate {certificate}")
            raise ValueError(f"invalid certificate {certificate}")

        for ca_prefix in sorted(ca_set_prefix):
            certs_list = [
                self._certs_dir / c.name
                for c in self._certs_dir.glob(f"{ca_prefix}.*.pem")
            ]

            store = crypto.X509Store()
            for c in certs_list:
                logger.info(f"cert {c}")
                store.add_cert(load_pem(c.read_bytes()))

            try:
                store_ctx = crypto.X509StoreContext(store, cert_to_verify)
                store_ctx.verify_certificate()
                logger.info(f"verfication succeeded against: {ca_prefix}")
                return
            except crypto.X509StoreContextError as e:
                logger.info(f"verify against {ca_prefix} failed: {e}")

        logger.error(f"certificate {certificate} could not be verified")
        raise ValueError(f"certificate {certificate} could not be verified")


# meta files entry classes


def de_escape(s: str) -> str:
    return s.replace(r"'\''", r"'")


@dataclass
class _BaseInf:
    """Base class for dir, symlink, persist entry."""

    mode: int
    uid: int
    gid: int
    _left: str = field(init=False, compare=False, repr=False)

    _base_pattern: ClassVar[re.Pattern] = re.compile(
        r"(?P<mode>\d+),(?P<uid>\d+),(?P<gid>\d+),(?P<left_over>.*)"
    )

    def __init__(self, info: str):
        match_res: Optional[re.Match] = self._base_pattern.match(info.strip())
        assert match_res is not None, f"match base_inf failed: {info}"

        self.mode = int(match_res.group("mode"), 8)
        self.uid = int(match_res.group("uid"))
        self.gid = int(match_res.group("gid"))
        self._left: str = match_res.group("left_over")


@dataclass
class DirectoryInf(_BaseInf):
    """Directory file information class for dirs.txt.
    format: mode,uid,gid,'dir/name'

    NOTE: only use path for hash key
    """

    path: Path

    def __init__(self, info):
        super().__init__(info)
        self.path = Path(de_escape(self._left[1:-1]))

        del self._left

    def __eq__(self, _other: Any) -> bool:
        if isinstance(_other, DirectoryInf):
            return _other.path == self.path
        elif isinstance(_other, Path):
            return _other == self.path
        else:
            return False

    def __hash__(self) -> int:
        return hash(self.path)

    def mkdir_relative_to_mount_point(self, mount_point: Union[Path, str]):
        _target = Path(mount_point) / self.path.relative_to("/")
        _target.mkdir(parents=True, exist_ok=True)
        os.chmod(_target, self.mode)
        os.chown(_target, self.uid, self.gid)


@dataclass
class SymbolicLinkInf(_BaseInf):
    """Symbolik link information class for symlinks.txt.

    format: mode,uid,gid,'path/to/link','path/to/target'
    example:
    """

    slink: Path
    srcpath: Path

    _pattern: ClassVar[re.Pattern] = re.compile(
        r"'(?P<link>.+)((?<!\')',')(?P<target>.+)'"
    )

    def __init__(self, info):
        super().__init__(info)
        res = self._pattern.match(self._left)
        assert res is not None, f"match symlink failed: {info}"

        self.slink = Path(de_escape(res.group("link")))
        self.srcpath = Path(de_escape(res.group("target")))

        del self._left

    def link_at_mount_point(self, mount_point: Union[Path, str]):
        # NOTE: symbolic link in /boot directory is not supported. We don't use it.
        _newlink = Path(mount_point) / self.slink.relative_to("/")
        _newlink.symlink_to(self.srcpath)
        # set the permission on the file itself
        os.chown(_newlink, self.uid, self.gid, follow_symlinks=False)


@dataclass
class PersistentInf:
    """Persistent file information class for persists.txt

    format: 'path'
    """

    path: Path

    def __init__(self, info: str):
        self.path = Path(de_escape(info.strip()[1:-1]))


class RegularInf:
    """RegularInf scheme for regulars.txt.

    format: mode,uid,gid,link number,sha256sum,'path/to/file'[,size[,inode]]
    example: 0644,1000,1000,1,0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,'path/to/file',1234,12345678

    Attrs:
        mode: int
        uid: int
        gid: int
        nlink: int
        sha256hash: str
        _base: str
        path: Path
        size: Optional[int] = None
        inode: Optional[str] = None

    NOTE: size and inode sections are both optional, if inode exists, size must exist.
    NOTE 2: path should always be relative to '/', not relative to any mount point!
    """

    __slots__ = ("_ma",)

    _ma: re.Match
    _reginf_pa: ClassVar[re.Pattern] = re.compile(
        r"(?P<mode>\d+),(?P<uid>\d+),(?P<gid>\d+),(?P<nlink>\d+),(?P<hash>\w+),'(?P<path>.+)'(,(?P<size>\d+)(,(?P<inode>\d+))?)?"
    )

    def __init__(self, _input: str) -> None:
        _ma = self._reginf_pa.match(_input)
        assert _ma is not None, f"matching reg_inf failed for {_input}"
        self._ma = _ma

    @classmethod
    def parse_reginf(cls, _input: str) -> "RegularInf":
        return cls(_input)

    @property
    def base(self) -> str:
        return "/boot" if self._ma.group("path").startswith("/boot") else "/"

    @property
    def mode(self) -> int:
        return int(self._ma.group("mode"), 8)

    @property
    def uid(self) -> int:
        return int(self._ma.group("uid"))

    @property
    def gid(self) -> int:
        return int(self._ma.group("gid"))

    @property
    def nlink(self) -> int:
        return int(self._ma.group("nlink"))

    @property
    def size(self) -> Optional[int]:
        if res := self._ma.group("size"):
            return int(res)

    @property
    def inode(self) -> Optional[str]:
        if res := self._ma.group("inode"):
            return res

    @property
    def sha256hash(self):
        return self._ma.group("hash")

    @property
    def path(self) -> str:
        return self._ma.group("path")

    def make_relative_to_mount_point(self, mp) -> Path:
        return Path(mp) / os.path.relpath(self.path, self.base)

    def verify_file(self, *, src_mount_point: Union[Path, str]) -> bool:
        """Verify file that with the path relative to <src_mount_point>."""
        return verify_file(
            self.make_relative_to_mount_point(src_mount_point),
            self.sha256hash,
            self.size,
        )

    def copy_relative_to_mount_point(
        self, dst_mount_point: Union[Path, str], /, *, src_mount_point: Path
    ):
        """Copy file to the path that relative to dst_mount_point, from src_mount_point."""
        _src = self.make_relative_to_mount_point(src_mount_point)
        _dst = self.make_relative_to_mount_point(dst_mount_point)
        shutil.copy2(_src, _dst, follow_symlinks=False)
        # still ensure permission on dst
        os.chown(_dst, self.uid, self.gid)
        os.chmod(_dst, self.mode)

    def copy_to_dst(self, dst: Union[Path, str], /, *, src_mount_point: Path):
        """Copy file pointed by self to the dst."""
        _src = self.make_relative_to_mount_point(src_mount_point)
        shutil.copy2(_src, dst, follow_symlinks=False)
        # still ensure permission on dst
        os.chown(dst, self.uid, self.gid)
        os.chmod(dst, self.mode)

    def copy_from_src(self, src: Union[Path, str], *, dst_mount_point: Path):
        """Copy file from src to dst pointed by regular_inf."""
        _dst = self.make_relative_to_mount_point(dst_mount_point)
        shutil.copy2(src, _dst, follow_symlinks=False)
        # still ensure permission on dst
        os.chown(_dst, self.uid, self.gid)
        os.chmod(_dst, self.mode)

    def move_from_src(self, src: Union[Path, str], *, dst_mount_point: Path):
        """Copy file from src to dst pointed by regular_inf."""
        _dst = self.make_relative_to_mount_point(dst_mount_point)
        shutil.move(str(src), _dst)
        # still ensure permission on dst
        os.chown(_dst, self.uid, self.gid)
        os.chmod(_dst, self.mode)


class UniqueRegInfByPath:
    __slots__ = ("reginf",)

    def __init__(self, _reginf: RegularInf) -> None:
        self.reginf = _reginf

    def __hash__(self) -> int:
        return hash(self.reginf.path)

    def __eq__(self, _other) -> bool:
        """
        NOTE: also take Path as _other
        """
        if isinstance(_other, (Path, str)):
            return self.reginf.path == str(_other)
        if isinstance(_other, self.__class__):
            return self.reginf.path == _other.reginf.path
        return False


class UniqueRegInfByHash:
    __slots__ = ("reginf",)

    def __init__(self, _reginf: RegularInf) -> None:
        self.reginf = _reginf

    def __hash__(self) -> int:
        return hash(self.reginf.sha256hash)

    def __eq__(self, _other) -> bool:
        """
        NOTE: also take Path as _other
        """
        if isinstance(_other, Sha256hashAsPyHash):
            return self.reginf.sha256hash == _other
        if isinstance(_other, self.__class__):
            return self.reginf.sha256hash == _other.reginf.sha256hash
        return False


class Sha256hashAsPyHash(str):
    def __hash__(self) -> int:
        return int(self, base=16)


class UniquePathBucket(Set[UniqueRegInfByPath]):
    def iter_entries(self) -> Iterator[Tuple[bool, UniqueRegInfByPath]]:
        _len, _count = len(self), 0
        for entry in self:
            _count += 1
            yield _count == _len, entry


class RegInfDelta:
    def __init__(self) -> None:
        self._unique_path: Dict[UniqueRegInfByPath, UniqueRegInfByPath] = dict()
        self._hash_bucket: DefaultDict[
            Sha256hashAsPyHash, UniquePathBucket
        ] = defaultdict(UniquePathBucket)

    def add(self, _reginf: RegularInf):
        _unique_path = UniqueRegInfByPath(_reginf)

        self._unique_path[_unique_path] = _unique_path
        self._hash_bucket[_reginf.sha256hash].add(_unique_path)

    def remove_bucket(self, _hash: Sha256hashAsPyHash):
        _poped = self._hash_bucket.pop(_hash)
        for _path in _poped:
            self._unique_path.pop(_path)

    def contains_path(self, _path: Union[Path, str]) -> bool:
        return str(_path) in self._unique_path

    def contains_hash(self, _hash: Sha256hashAsPyHash) -> bool:
        return _hash in self._hash_bucket

    def get_reginf_by_path(self, _path: Union[Path, str]) -> RegularInf:
        return self._unique_path[str(_path)]  # type: ignore

    def iter_pop_bucket(
        self,
    ) -> Iterator[Tuple[Sha256hashAsPyHash, UniquePathBucket]]:
        while True:
            try:
                _hash, _bucket = self._hash_bucket.popitem()
                for _path in _bucket:
                    self._unique_path.pop(_path)
                yield _hash, _bucket
            except KeyError:
                break
