# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This project exists to verify compiled NEO3 smart contracts output.

## Commands

```bash
# Run all tests
make test
# Equivalent to:
python -m unittest discover -v -s examples/
python -m unittest discover -v -s tests/

# Run a single test file
python -m unittest examples/nep17/test_nep17.py -v

# Type checking
make type        # runs mypy on boaconstructor/

# Code formatting
make black       # applies black formatter

# Build wheel
make build       # builds + fixes platform tags via scripts/fix-wheels.py
```

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -e .[dev]
cd scripts && python download-node.py   # downloads neo-go binary into boaconstructor/data/
```

## Architecture

**boa-test-constructor** is a Python unittest framework for testing NEO3 smart contracts. Tests run against a local in-memory neo-go blockchain node, so results match the real network.

### Core modules (`boaconstructor/`)

**`__init__.py`** — `SmartContractTestCase` is the primary class users inherit from. It extends `unittest.IsolatedAsyncioTestCase`, meaning all test methods must be `async`. Key methods:
- `deploy(path_to_nef)` — deploys a contract; resolves relative paths by inspecting `inspect.stack()[1]` (caller's frame)
- `call(contract_hash, method, params, return_type, signing_accounts)` — invokes a contract method; if `signing_accounts` is provided, persists state; otherwise test-invokes
- `transfer(token, source, dest, amount)` — NEP-17 token transfer
- `get_storage(contract_hash, prefix, key_postprocessor, value_postprocessor)` — query contract storage

Errors from contract execution raise `AssertException` or `AbortException`.

**`node.py`** — `NeoGoNode` manages the neo-go subprocess. It starts the node, sets up `ChainFacade` (from neo-mamba) for RPC, parses stdout to capture `System.Runtime.Log` entries (stored as `RuntimeLog` dataclasses). The node uses an in-memory DB (no explicit reset between tests needed).

**`storage.py`** — Post-processor utilities for deserializing raw storage values: `as_uint160()`, `as_uint256()`, `as_int()`, `as_str()`, `as_address()`, `as_public_key()`, `stdlib_deserialize()`.

### Test structure

Tests go in `examples/` or `tests/`. Each test folder has a `resources/` subdirectory containing compiled `.nef` + `.manifest.json` smart contract files. The test runner discovers tests via `unittest discover`.

### Bundled binary

A platform-specific neo-go v0.116.0 binary lives in `boaconstructor/data/neogo`. The `scripts/download-node.py` script fetches it from GitHub releases. The version is configured in `pyproject.toml` under `[tool.neogo]`.

### Wheel building

`scripts/fix-wheels.py` rewrites platform tags on Linux wheels to `manylinux1` for PyPI compliance after `python -m build`.

## Writing tests

### Rules

- **Coverage:** When the smart contract source is available, maximize code coverage — identify every distinct code path (branches, loops, conditionals) and write a test for each. If source is not available, ask for it before writing tests.
- **Edge cases:** Always include edge cases where applicable. For numeric inputs: test 0, 1, negative values, and larger values. For loops: test 0 iterations, 1 iteration, and multiple iterations. For conditionals: test each branch.
- **Docstrings:** Add a short docstring when a test method's name is not fully self-explanatory or the logic is complex. Skip when the name already conveys the full intent.

### Test file structure

```python
import asyncio
from boaconstructor import SmartContractTestCase, AssertException, AbortException
from neo3.wallet import account

class MyContractTest(SmartContractTestCase):
    genesis: account.Account

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        asyncio.run(cls.asyncSetupClass())

    @classmethod
    async def asyncSetupClass(cls) -> None:
        cls.genesis = cls.node.wallet.account_get_by_label("committee")  # type: ignore
        cls.contract_hash = await cls.deploy("./my_contract.nef", cls.genesis)

    async def test_something(self):
        result, _ = await self.call("method_name", [arg], return_type=int)
        self.assertEqual(expected, result)
```

### Calling contracts

```python
# Read-only (no state change) — omit signing_accounts
result, notifications = await self.call("method", [arg], return_type=int)

# State-persisting — pass signing_accounts
result, notifications = await self.call("method", [arg], return_type=None, signing_accounts=[self.user1])
```

Supported `return_type` values: `int`, `str`, `bool`, `dict`, `list`, `bytes`, `None`, `types.UInt160`, `types.UInt256`, `cryptography.ECPoint`.

### Entry point naming

For single-function contracts the entry point is `"main"`. For multi-function contracts the method name matches the Python function name. When uncertain, check the contract's `.manifest.json` — the `abi.methods` array lists all entry points.

### Error cases

```python
with self.assertRaises(AssertException) as ctx:
    await self.call("method", [arg], return_type=int)
self.assertIn("expected message", str(ctx.exception))
```

Use `AssertException` for `assert` failures, `AbortException` for `abort()` failures.

### NEF file location and deployment

The `.nef` and its matching `.manifest.json` must be in the same directory. Pass a path relative to the test file — `deploy()` resolves it via `inspect.stack()`, not the working directory.

```python
cls.contract_hash = await cls.deploy("./resources/my_contract.nef", cls.genesis)
```

### Accounts and token helpers

```python
cls.genesis = cls.node.wallet.account_get_by_label("committee")   # pre-funded committee account
cls.user1   = cls.node.wallet.account_new("password", "label")    # create a new test account

from neo3.contracts.contract import CONTRACT_HASHES
GAS = CONTRACT_HASHES.GAS_TOKEN
NEO = CONTRACT_HASHES.NEO_TOKEN

# Fund an account
await cls.transfer(GAS, cls.genesis.script_hash, cls.user1.script_hash, amount, decimals=8)
```
