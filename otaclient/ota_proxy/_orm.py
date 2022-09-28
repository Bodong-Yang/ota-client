from dataclasses import asdict, astuple, dataclass, fields
from typing import Any, Dict, List, Optional, Tuple, Type, Generic, TypeVar, Union


SQLITE_DATATYPES = Union[
    int,  # INTEGER
    str,  # TEXT
    float,  # REAL
    bytes,  # BLOB
    bool,  # INTEGER 0, 1
    # NOTE: not introduce NULL type now!
    # type(None),  # NULL
]
FV = TypeVar("FV", bound=SQLITE_DATATYPES)  # field value type


@dataclass
class ColumnDescriptor(Generic[FV]):
    type_guard: bool
    field_type: Type[FV]

    def __init__(
        self,
        field_type: Type[FV],
        constrains: str,
        *,
        type_guard=False,
        default=None,
    ) -> None:
        self.type_guard = type_guard
        self.field_type = field_type
        self.constrains = constrains
        self._default = default if default is not None else self.field_type()
        super().__init__()

    def __get__(self, obj, objtype=None) -> Union[FV, "ColumnDescriptor"]:
        if obj is not None:
            return getattr(obj, self.private_name)
        if obj is None and objtype:
            # NOTE: align to the behavior of dataclass setting default value:
            #       To determine whether a field contains a default value,
            #       dataclasses will call the descriptor’s __get__ method
            #       using its class access form (i.e. descriptor.__get__(obj=None, type=cls).
            #       If the descriptor returns a value in this case,
            #       it will be used as the field’s default.
            return self._default
        return self

    def __set__(self, obj, value):
        if self.type_guard and not isinstance(value, self.field_type):
            raise TypeError(f"type_guard: expect {self.field_type}, get {type(value)}")
        # apply default type conversion or type default value
        setattr(obj, self.private_name, self.field_type(value))  # type: ignore

    def __set_name__(self, owner: Type[Any], name: str):
        self.field_name = name
        self.private_name = f"_{name}"

    def check_type(self, value: Any) -> bool:
        return isinstance(value, self.field_type)


@dataclass
class ORMBase(Generic[FV]):
    @classmethod
    def row_to_meta(cls, row: Optional[Dict[str, FV]]):
        if not row:  # return empty cachemeta on empty input
            return cls()
        # only pick recongized cols' value
        _parsed_row = {}
        for field in fields(cls):
            field_name = field.name
            if field_name in row:
                _parsed_row[field_name] = row[field_name]
        return cls(**_parsed_row)

    @classmethod
    def get_create_table_stmt(cls, table_name: str) -> str:
        _col_descriptors: List[ColumnDescriptor] = [
            getattr(cls, field.name) for field in fields(cls)
        ]
        return (
            f"CREATE TABLE {table_name}("
            + ", ".join(
                [f"{col.field_name} {col.constrains}" for col in _col_descriptors]
            )
            + ")"
        )

    @classmethod
    def get_col(cls, name: str) -> Optional[ColumnDescriptor]:
        try:
            return getattr(cls, name)
        except AttributeError:
            return

    @classmethod
    def contains_field(cls, _input: Union[str, ColumnDescriptor]) -> bool:
        try:
            if isinstance(_input, ColumnDescriptor):
                _input = _input.field_name
            return isinstance(getattr(cls, _input), ColumnDescriptor)
        except AttributeError:
            return False

    @classmethod
    def get_shape(cls) -> str:
        return ",".join(["?"] * len(fields(cls)))

    def to_tuple(self) -> Tuple[FV]:
        return astuple(self)

    def to_dict(self) -> Dict[str, FV]:
        return asdict(self)
