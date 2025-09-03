import asyncio
from boaconstructor import (
    AbortException,
    AssertException,
    SmartContractTestCase,
    Nep17TransferEvent,
    storage as _storage,
)
from neo3.api.wrappers import NEP17Contract
from neo3.wallet import account
from neo3.core import types
from neo3.contracts.contract import CONTRACT_HASHES
from typing import cast

NEO = CONTRACT_HASHES.NEO_TOKEN
GAS = CONTRACT_HASHES.GAS_TOKEN


class Nep17ContractTest(SmartContractTestCase):
    genesis: account.Account
    user1: account.Account
    user2: account.Account
    balance_prefix: bytes = b"b"
    contract: NEP17Contract

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.user1 = cls.node.wallet.account_new("alice")
        cls.user2 = cls.node.wallet.account_new("bob")
        # Due to a lack of an asyncSetupClass we have to do it manually
        # Use this if you for example want to initialise some blockchain state

        # asyncio.run() works because the `IsolatedAsyncioTestCase` class we inherit from
        # hasn't started its own loop yet
        asyncio.run(cls.asyncSetupClass())

    @classmethod
    async def asyncSetupClass(cls) -> None:
        cls.genesis = cls.node.wallet.account_get_by_label("committee")  # type: ignore
        cls.contract_hash = await cls.deploy("./resources/nep17.nef", cls.genesis)
        cls.contract = NEP17Contract(cls.contract_hash)
        await cls.transfer(GAS, cls.genesis.script_hash, cls.user1.script_hash, 100, 8)
        await cls.transfer(GAS, cls.genesis.script_hash, cls.user2.script_hash, 100, 8)

    async def test_symbol(self):
        expected = "NEP17"
        result, _ = await self.call("symbol", return_type=str)
        # Alternative approach using mamba's wrappers because we know this is a Nep17Contract
        # result = await self.facade.test_invoke(self.contract.symbol())
        self.assertEqual(expected, result)

    async def test_decimals(self):
        expected = 8
        result, _ = await self.call("decimals", return_type=int)
        self.assertEqual(expected, result)

    async def test_01_total_supply(self):
        expected = 1_000_000_000_000_000
        result, _ = await self.call("totalSupply", return_type=int)
        self.assertEqual(expected, result)

    async def test_02_balance_of(self):
        contract_decimals = 8
        expected = 100 * (10**contract_decimals)

        # first mint tokens
        success, _ = await self.transfer(
            GAS,
            self.user1.script_hash,
            self.contract_hash,
            50,
            8,
            signing_account=self.user1,
        )
        self.assertTrue(success)
        storage = cast(
            dict[types.UInt160, bytes],
            await self.get_storage(
                prefix=self.balance_prefix,
                remove_prefix=True,
                key_post_processor=_storage.as_uint160,
            ),
        )
        result, _ = await self.call(
            "balanceOf", [self.user1.script_hash], return_type=int
        )
        self.assertEqual(expected, result)
        balance_key = self.user1.script_hash
        self.assertIn(balance_key, storage)
        self.assertEqual(types.BigInteger(expected).to_array(), storage[balance_key])

        # now test with an account that doesn't exist
        expected = 0
        unknown_account = types.UInt160(b"\x01" * 20)
        result, _ = await self.call("balanceOf", [unknown_account], return_type=int)
        self.assertEqual(expected, result)
        balance_key = unknown_account
        self.assertNotIn(balance_key, storage)

        # now test invalid account
        bad_account = b"\x01"

        with self.assertRaises(AssertException) as context:
            await self.call("balanceOf", [bad_account], return_type=int)

        self.assertIn("invalid account", str(context.exception))

    async def test_03_transfer_success(self):
        # test we have existing balance
        user1_balance, _ = await self.call(
            "balanceOf", [self.user1.script_hash], return_type=int
        )
        self.assertGreater(user1_balance, 0)

        # now transfer to another account
        success, notifications = await self.call(
            "transfer",
            [self.user1.script_hash, self.user2.script_hash, user1_balance, None],
            return_type=bool,
            signing_accounts=[self.user1],
        )

        self.assertTrue(success)
        self.assertEqual(1, len(notifications))
        self.assertEqual("Transfer", notifications[0].event_name)

        storage = cast(
            dict[types.UInt160, bytes],
            await self.get_storage(
                prefix=self.balance_prefix,
                remove_prefix=True,
                key_post_processor=_storage.as_uint160,
            ),
        )

        # test we emitted the correct transfer event
        event = Nep17TransferEvent.from_notification(notifications[0])
        self.assertEqual(self.user1.script_hash, event.source)
        self.assertEqual(self.user2.script_hash, event.destination)
        self.assertEqual(user1_balance, event.amount)

        # test balance updates
        user2_balance, _ = await self.call(
            "balanceOf", [self.user2.script_hash], return_type=int
        )
        self.assertEqual(user1_balance, user2_balance)

        # test storage updates
        self.assertNotIn(self.user1.script_hash, storage)
        self.assertIn(self.user2.script_hash, storage)
        self.assertEqual(
            types.BigInteger(user1_balance).to_array(), storage[self.user2.script_hash]
        )

    async def test_onnep17(self):
        with self.assertRaises(AbortException) as context:
            await self.transfer(
                NEO,
                self.genesis.script_hash,
                self.contract_hash,
                10,
                0,
                signing_account=self.genesis,
            )
        self.assertEqual("contract only accepts GAS", str(context.exception))
