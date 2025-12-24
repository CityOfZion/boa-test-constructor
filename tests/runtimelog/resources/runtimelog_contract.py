from boa3.sc.compiletime import public


@public
def print_str(msg: str):
    print(msg)

@public
def print_bytes(msg: bytes):
    print(msg)

@public
def print_list(msg: list):
    print(msg)
