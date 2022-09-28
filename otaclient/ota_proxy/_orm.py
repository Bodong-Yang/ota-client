from dataclasses import asdict, astuple, dataclass, fields
from typing import Any, Dict, List, Optional, Tuple, Type, Generic, TypeVar, Union


SQLITE_DATATYPES = Union[
    int,  # INTEGER
    str,  # TEXT
    float,  # REAL
    bytes,  # BLOB
    bool,  # INTEGER 0, 1
    type(None),  # NULL
]
FV = TypeVar("FV", bound=SQLITE_DATATYPES)  # field value type


class Column(Generic[FV]):
    type_guard: bool
    field_type: Type[FV]

    def __init__(
        self, field_type: Type[FV], constrains: str, *, type_guard=False
    ) -> None:
        self.type_guard = type_guard
        self.field_type = field_type
        self.constrains = constrains
        super().__init__()

    def __get__(self, obj, objtype=None) -> Union[FV, "Column"]:
        if obj is not None:
            return getattr(obj, self.private_name)
        return self

    def __set__(self, obj, value: Any):
        # during dataclass default value initializing,
        # or input type is Type[None](NULL)
        if isinstance(value, type(self)) or value is None:
            value = self.field_type()  # type: ignore
        if self.type_guard and not isinstance(value, self.field_type):
            raise TypeError(f"type_guard: expect {self.field_type}, get {type(value)}")
        # apply default type conversion or type default value
        setattr(obj, self.private_name, value)

    def __set_name__(self, owner: Type[Any], name: str):
        self.field_name = name
        self.private_name = f"_{name}"


@dataclass
class ORMBase(Generic[FV]):
    @classmethod
    def get_columns(cls) -> List[str]:
        return [f.name for f in fields(cls)]

    @classmethod
    def get_shape(cls) -> str:
        return ",".join(["?"] * len(fields(cls)))

    @classmethod
    def row_to_meta(cls, row: Optional[Dict[str, FV]]):
        if not row:  # return empty cachemeta on empty input
            return cls()
        # filter away unexpected columns
        _parsed_row = {k: v for k, v in row.items() if k in set(cls.get_columns())}
        return cls(**_parsed_row)

    @classmethod
    def get_create_table_stmt(cls, table_name: str) -> str:
        _col_descriptors: List[Column] = [
            getattr(cls, field_name) for field_name in set(cls.get_columns())
        ]
        return (
            f"CREATE TABLE {table_name}("
            + ", ".join(
                [f"{col.field_name} {col.constrains}" for col in _col_descriptors]
            )
            + ")"
        )

    def to_tuple(self) -> Tuple[FV]:
        return astuple(self)

    def to_dict(self) -> Dict[str, FV]:
        return asdict(self)
