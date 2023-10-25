import pathlib
import unittest
import asyncio
import enum
import signal
import re
from typing import Optional, TypeVar, Type, cast, Sequence
from neo3.core import types, cryptography
from neo3.wallet import account
from neo3.api.wrappers import GenericContract, NEP17Contract, ChainFacade
from neo3.api import noderpc
from neo3.network.payloads.verification import Signer
from neo3.api.helpers.signing import (
    sign_insecure_with_account,
    sign_insecure_with_multisig_account,
)
from neo3.api.helpers import unwrap
from neo3.contracts.contract import CONTRACT_HASHES
from neo3.contracts import nef, manifest
from dataclasses import dataclass
from boaconstructor.node import NeoGoNode, Node

ASSERT_REASON = re.compile(r".*Reason: (.*)")


class AssertException(Exception):
    pass


class AbortException(Exception):
    pass


# TODO: include ability to read gas consumption
# TODO: add ability to provide witness for call()
# TODO: see how to test check_witness

T = TypeVar("T")


class Token(enum.Enum):
    NEO = 0
    GAS = 1


class SmartContractTestCase(unittest.IsolatedAsyncioTestCase):
    # TODO: make configurable
    node: Node = NeoGoNode("resources/protocol.unittest.yml")
    contract_hash: types.UInt160

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # disable debug mode because it will warn about functions waiting longer than 0.1 seconds
        # which will be the case for all functions that persist state (e.g. transfer())
        asyncio.get_event_loop().set_debug(False)

    @property
    def facade(self) -> ChainFacade:
        return self.node.facade

    @classmethod
    def setUpClass(cls) -> None:
        cls.addClassCleanup(cls.node.reset)
        cls.addClassCleanup(cls.node.stop)

        def cleanup(unused_sig, unused_frame):
            cls.node.stop()
            cls.node.reset()

        signal.signal(signal.SIGINT, cleanup)

        cls.node.start()

    @classmethod
    async def call(
        cls,
        method: str,
        args: list = None,
        *,
        return_type: Type[T],
        signing_accounts: Optional[Sequence[account.Account]] = None,
        signers: Optional[Sequence[Signer]] = None,
        target_contract: Optional[types.UInt160] = None,
    ) -> tuple[T, list[noderpc.Notification]]:
        """
        Calls the contract specified by `contract_hash`

        Args:
            method: name of the method to call
            args: method arguments
            return_type: expected return type. Will be used to unwrap and cast the results.
            signing_accounts:
                If not specified a 'test_invoke' will be performed.
                If specified an 'invoke' (=state persisting) will be performed. The default witness scope is CALLED_BY_ENTRY.
                This can be overridden using the `signers` argument.
            signers: a list of custom signers. Must have the same length as `signing_account` if that is specified.
            target_contract: call a different contract than the one under test. e.g. NeoToken
        """
        if target_contract is None:
            contract = GenericContract(cls.contract_hash)
        else:
            contract = GenericContract(target_contract)

        facade = cls.node.facade

        if signing_accounts is not None:
            signing_pairs = []

            if signers is not None and len(signers) != len(signing_accounts):
                raise ValueError(f"signing_accounts and signers length must be equal")

            for i, signing_account in enumerate(signing_accounts):
                if signers is None:
                    signer = Signer(signing_account.script_hash)
                else:
                    # take it from the supplied list
                    signer = signers[i]
                if signing_account.is_multisig:
                    signing_pairs.append(
                        (
                            sign_insecure_with_multisig_account(
                                signing_account, password="123"
                            ),
                            signer,
                        )
                    )
                else:
                    signing_pairs.append(
                        (
                            sign_insecure_with_account(signing_account, password="123"),
                            signer,
                        )
                    )
            receipt = await facade.invoke(
                contract.call_function(method, args), signers=signing_pairs
            )
            cls._check_vmstate(receipt)
            exec_result = receipt.result
            notifications = receipt.notifications
        else:
            receipt = await facade.test_invoke(
                contract.call_function(method, args), signers=signers
            )
            cls._check_vmstate(receipt)
            exec_result = receipt
            receipt.notifications = cast(
                noderpc.ExecutionResultResponse, receipt.notifications
            )
            notifications = receipt.notifications

        if return_type is str:
            return unwrap.as_str(exec_result), notifications
        elif return_type is int:
            return unwrap.as_int(exec_result), notifications
        elif return_type is bool:
            return unwrap.as_bool(exec_result), notifications
        elif return_type is dict:
            return unwrap.as_dict(exec_result), notifications
        elif return_type is list:
            return unwrap.as_list(exec_result), notifications
        elif return_type is types.UInt160:
            return unwrap.as_uint160(exec_result), notifications
        elif return_type is types.UInt256:
            return unwrap.as_uint256(exec_result), notifications
        elif return_type is bytes:
            return unwrap.as_bytes(exec_result), notifications
        elif return_type is cryptography.ECPoint:
            return unwrap.as_public_key(exec_result), notifications
        elif return_type is None:
            return unwrap.as_none(exec_result), notifications
        else:
            raise ValueError(f"unsupported return_type: {return_type}")

    @classmethod
    async def deploy(
        cls, path_to_nef: str, signing_account: account.Account
    ) -> types.UInt160:
        nef_path = pathlib.Path(path_to_nef)
        if not nef_path.is_file() or not nef_path.suffix == ".nef":
            raise ValueError("invalid contract path specified")
        _nef = nef.NEF.from_file(str(nef_path.absolute()))

        manifest_path = path_to_nef.replace(".nef", ".manifest.json")
        if not pathlib.Path(manifest_path).is_file():
            raise ValueError(f"can't find manifest at {manifest_path}")
        _manifest = manifest.ContractManifest.from_file(manifest_path)

        if signing_account.is_multisig:
            sign_pair = (
                sign_insecure_with_multisig_account(signing_account, password="123"),
                Signer(signing_account.script_hash),
            )

        else:
            sign_pair = (
                sign_insecure_with_account(signing_account, password="123"),
                Signer(signing_account.script_hash),
            )
        receipt = await cls.node.facade.invoke(
            GenericContract.deploy(_nef, _manifest), signers=[sign_pair]
        )
        return receipt.result

    @classmethod
    async def transfer(
        cls,
        neo_or_gas: Token,
        source: types.UInt160,
        destination: types.UInt160,
        amount: int,
        signing_account: Optional[account.Account] = None,
        system_fee: int = 0,
    ) -> bool:
        if neo_or_gas == Token.NEO:
            contract = NEP17Contract(CONTRACT_HASHES.NEO_TOKEN)
        else:
            contract = NEP17Contract(CONTRACT_HASHES.GAS_TOKEN)

        if signing_account is None:
            signing_account = cls.node.account_committee

        if signing_account.is_multisig:
            sign_pair = (
                sign_insecure_with_multisig_account(signing_account, password="123"),
                Signer(signing_account.script_hash),
            )

        else:
            sign_pair = (
                sign_insecure_with_account(signing_account, password="123"),
                Signer(signing_account.script_hash),
            )

        try:
            receipt = await cls.node.facade.invoke(
                contract.transfer_friendly(source, destination, amount),
                signers=[sign_pair],
                system_fee=system_fee,
            )
        except ValueError as e:
            if "ASSERT" in str(e):
                raise AssertException(cls._get_assert_reason(str(e)))
            elif "ABORT" in str(e):
                raise AbortException(cls._get_assert_reason(str(e)))
            else:
                raise e
        return receipt.result

    @classmethod
    def _check_vmstate(cls, receipt):
        try:
            unwrap.check_state_ok(receipt)
        except ValueError as e:
            if "ASSERT" in receipt.exception:
                raise AssertException(cls._get_assert_reason(receipt.exception))
            elif "ABORT" in receipt.exception:
                raise AbortException(cls._get_assert_reason(receipt.exception))
            else:
                raise e

    @classmethod
    def _get_assert_reason(self, exception: str):
        m = ASSERT_REASON.match(exception)
        if m is not None:
            return m.group(1)


@dataclass
class Nep17TransferEvent:
    source: types.UInt160
    destination: types.UInt160
    amount: int

    @classmethod
    def from_notification(cls, n: noderpc.Notification):
        stack = n.state.as_list()
        source = stack[0].as_uint160()
        destination = stack[1].as_uint160()
        amount = stack[2].as_int()
        return cls(source, destination, amount)
