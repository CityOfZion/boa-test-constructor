import asyncio
import math

from boaconstructor import AbortException, AssertException, SmartContractTestCase
from neo3.api.wrappers import GenericContract
from neo3.wallet import account
from neo3.core import types
from neo3.contracts.contract import CONTRACT_HASHES

NEO = CONTRACT_HASHES.NEO_TOKEN
GAS = CONTRACT_HASHES.GAS_TOKEN


class AmmContractTest(SmartContractTestCase):
    genesis: account.Account
    owner: account.Account
    user: account.Account

    zgas_contract_hash: types.UInt160
    zgas_contract: GenericContract
    zneo_contract_hash: types.UInt160
    zneo_contract: GenericContract

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.user = cls.node.wallet.account_new("123", "alice")
        cls.owner = cls.node.wallet.account_new("123", "owner")
        # Due to a lack of an asyncSetupClass we have to do it manually
        # Use this if you for example want to initialise some blockchain state

        # asyncio.run() works because the `IsolatedAsyncioTestCase` class we inherit from
        # hasn't started its own loop yet
        asyncio.run(cls.asyncSetupClass())

    @classmethod
    async def asyncSetupClass(cls) -> None:
        cls.genesis = cls.node.wallet.account_get_by_label("committee")

        await cls.transfer(GAS, cls.genesis.script_hash, cls.owner.script_hash, 100)
        await cls.transfer(GAS, cls.genesis.script_hash, cls.user.script_hash, 100)

        cls.contract_hash = await cls.deploy("./resources/amm.nef", cls.owner)
        cls.contract = GenericContract(cls.contract_hash)

        cls.zgas_contract_hash = await cls.deploy(
            "./resources/wrapped_gas.nef", cls.genesis
        )
        cls.zgas_contract = GenericContract(cls.zgas_contract_hash)

        cls.zneo_contract_hash = await cls.deploy(
            "./resources/wrapped_neo.nef", cls.genesis
        )
        cls.zneo_contract = GenericContract(cls.zneo_contract_hash)

    async def test_01_set_address(self):
        # won't work because it needs the owner signature
        set_address_wrong, _ = await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
        )
        self.assertFalse(set_address_wrong)

        # it will work now
        set_address_signed, _ = await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )
        self.assertTrue(set_address_signed)

        token_a, _ = await self.call("get_token_a", return_type=types.UInt160)
        self.assertEqual(token_a, self.zneo_contract_hash)

        token_b, _ = await self.call("get_token_b", return_type=types.UInt160)
        self.assertEqual(token_b, self.zgas_contract_hash)

        # initialize will work once
        set_address_again, _ = await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )
        self.assertFalse(set_address_again)

    async def test_02_symbol(self):
        symbol, _ = await self.call("symbol", return_type=str)
        self.assertEqual("AMM", symbol)

    async def test_03_decimals(self):
        decimals, _ = await self.call("decimals", return_type=int)
        self.assertEqual(8, decimals)

    async def test_04_total_supply(self):
        total_supply, _ = await self.call("totalSupply", return_type=int)
        self.assertEqual(0, total_supply)

    async def test_05_balance_of(self):
        balance_of_owner, _ = await self.call(
            "balanceOf", [self.owner.script_hash], return_type=int
        )
        self.assertEqual(0, balance_of_owner)

        # should fail when the script length is not 20
        with self.assertRaises(AssertException) as context:
            await self.call("balanceOf", [bytes(10)], return_type=int)
        self.assertIn("invalid account", str(context.exception))

        with self.assertRaises(AssertException) as context:
            await self.call("balanceOf", [bytes(30)], return_type=int)
        self.assertIn("invalid account", str(context.exception))

    async def test_06_quote(self):
        mock_amount_zneo = 1
        mock_reverse_zneo = 100
        mock_reverse_wgaz = 1100 * 10**8

        quote, _ = await self.call(
            "quote",
            [mock_amount_zneo, mock_reverse_zneo, mock_reverse_wgaz],
            return_type=int,
        )
        self.assertEqual(
            mock_amount_zneo * mock_reverse_wgaz // mock_reverse_zneo, quote
        )

    async def test_07_add_liquidity(self):
        mock_balance_zneo = 10_000_000
        mock_balance_zgas = 10_000_000
        zgas_decimals = 10**8
        transferred_amount_zneo = 10
        transferred_amount_zgas = 110
        await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )
        await self.transfer(
            NEO,
            self.genesis.script_hash,
            self.user.script_hash,
            mock_balance_zneo,
        )
        await self.transfer(
            GAS,
            self.genesis.script_hash,
            self.user.script_hash,
            mock_balance_zgas,
        )

        # minting zNEO to user
        transfer_zneo, _ = await self.transfer(
            NEO,
            self.user.script_hash,
            self.zneo_contract_hash,
            mock_balance_zneo,
            signing_account=self.user,
        )
        # minting zGAS to user
        transfer_zgas, _ = await self.transfer(
            GAS,
            self.user.script_hash,
            self.zgas_contract_hash,
            mock_balance_zgas,
            signing_account=self.user,
        )

        self.assertTrue(transfer_zneo)
        self.assertTrue(transfer_zgas)

        # won't work, because the user did not allow the amm to transfer zNEO and zGAS
        with self.assertRaises(AssertException) as context:
            await self.call(
                "add_liquidity",
                [
                    transferred_amount_zneo,
                    transferred_amount_zgas,
                    0,
                    0,
                    self.user.script_hash,
                ],
                return_type=list,
                signing_accounts=[self.user],
            )
        self.assertEqual("not allowed", str(context.exception))

        # approving the AMM contract, so that it will be able to transfer zNEO from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, mock_balance_zneo],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zneo_contract_hash,
        )
        # approving the AMM contract, so that it will be able to transfer zGAS from user
        approve_zgas, _ = await self.call(
            "approve",
            [
                self.user.script_hash,
                self.contract_hash,
                mock_balance_zgas * zgas_decimals,
            ],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zgas_contract_hash,
        )
        self.assertTrue(approve_zneo)
        self.assertTrue(approve_zgas)

        # saving data to demonstrate that the value will change later
        total_supply_before, _ = await self.call("totalSupply", return_type=int)
        balance_user_amm_before, _ = await self.call(
            "balanceOf", [self.user.script_hash], return_type=int
        )
        reserves_before, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        liquidity = int(
            math.sqrt(transferred_amount_zneo * transferred_amount_zgas * zgas_decimals)
        )

        # adding liquidity to the pool will give you AMM tokens in return
        add_liquidity_result, notifications = await self.call(
            "add_liquidity",
            [
                transferred_amount_zneo,
                transferred_amount_zgas * zgas_decimals,
                0,
                0,
                self.user.script_hash,
            ],
            return_type=list,
            signing_accounts=[self.user],
        )
        for index, result in enumerate(add_liquidity_result):
            add_liquidity_result[index] = result.as_int()
        self.assertEqual(
            [
                transferred_amount_zneo,
                transferred_amount_zgas * zgas_decimals,
                liquidity,
            ],
            add_liquidity_result,
        )

        # data that will be compared with the previously saved data
        total_supply_after, _ = await self.call("totalSupply", return_type=int)
        balance_user_amm_after, _ = await self.call(
            "balanceOf", [self.user.script_hash], return_type=int
        )
        reserves_after, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        self.assertEqual(total_supply_before + liquidity, total_supply_after)
        self.assertEqual(balance_user_amm_before + liquidity, balance_user_amm_after)
        self.assertEqual(
            reserves_before[0].as_int() + transferred_amount_zneo,
            reserves_after[0].as_int(),
        )
        self.assertEqual(
            reserves_before[1].as_int() + transferred_amount_zgas * zgas_decimals,
            reserves_after[1].as_int(),
        )
        self.assertEqual(
            balance_user_zneo_before - transferred_amount_zneo, balance_user_zneo_after
        )
        self.assertEqual(
            balance_user_zgas_before - (transferred_amount_zgas * zgas_decimals),
            balance_user_zgas_after,
        )
        self.assertEqual(reserves_before[0].as_int(), balance_amm_zneo_before)
        self.assertEqual(reserves_before[1].as_int(), balance_amm_zgas_before)
        self.assertEqual(reserves_after[0].as_int(), balance_amm_zneo_after)
        self.assertEqual(reserves_after[1].as_int(), balance_amm_zgas_after)

        transfer_events = []
        sync_events = []
        mint_events = []
        for event in notifications:
            if event.contract == self.contract_hash:
                if event.event_name == "Transfer":
                    transfer_events.append(event)
                elif event.event_name == "Sync":
                    sync_events.append(event)
                elif event.event_name == "Mint":
                    mint_events.append(event)

        self.assertEqual(1, len(transfer_events))
        self.assertEqual(3, len(transfer_events[0].state.as_list()))
        sender, receiver, amount = transfer_events[0].state.as_list()
        self.assertEqual(None, sender.as_none())
        self.assertEqual(self.user.script_hash, receiver.as_uint160())
        self.assertEqual(liquidity, amount.as_int())

        self.assertEqual(1, len(sync_events))
        self.assertEqual(2, len(sync_events[0].state.as_list()))
        balance_zneo, balance_zgas = sync_events[0].state.as_list()
        self.assertEqual(transferred_amount_zneo, balance_zneo.as_int())
        self.assertEqual(transferred_amount_zgas * zgas_decimals, balance_zgas.as_int())

        self.assertEqual(1, len(mint_events))
        self.assertEqual(3, len(mint_events[0].state.as_list()))
        address, amount_zneo, amount_zgas = mint_events[0].state.as_list()
        self.assertEqual(self.user.script_hash, address.as_uint160())
        self.assertEqual(transferred_amount_zneo, amount_zneo.as_int())
        self.assertEqual(transferred_amount_zgas * zgas_decimals, amount_zgas.as_int())

        transferred_amount_zneo = 2
        transferred_amount_zgas = 23 * 10**8

        # approving the AMM contract, so that it will be able to transfer zNEO from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zneo],
            return_type=bool,
            target_contract=self.zneo_contract_hash,
            signing_accounts=[self.user],
        )
        # approving the AMM contract, so that it will be able to transfer zGAS from user
        approve_zgas, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zgas],
            return_type=bool,
            target_contract=self.zgas_contract_hash,
            signing_accounts=[self.user],
        )
        self.assertTrue(approve_zneo)
        self.assertTrue(approve_zgas)

        # saving data to demonstrate that the value will change later
        total_supply_before, _ = await self.call("totalSupply", return_type=int)
        reserves_before, _ = await self.call("get_reserves", return_type=list)

        # adding liquidity to the pool will give you AMM tokens in return
        add_liquidity_result, notifications = await self.call(
            "add_liquidity",
            [
                transferred_amount_zneo,
                transferred_amount_zgas * zgas_decimals,
                0,
                0,
                self.user.script_hash,
            ],
            return_type=list,
            signing_accounts=[self.user],
        )

        # zGAS will be quoted to keep the same ratio between zNEO and zGAS, the current ratio is 1 NEO to 11 GAS,
        # therefore, if 2 NEO are being added to the AMM, 22 GAS will be added instead of 23
        transferred_amount_zgas_quoted = (
            transferred_amount_zneo
            * reserves_before[1].as_int()
            // reserves_before[0].as_int()
        )

        # since there are tokens in the pool already, liquidity will be calculated as follows
        liquidity = min(
            transferred_amount_zneo
            * total_supply_before
            // reserves_before[0].as_int(),
            transferred_amount_zgas_quoted
            * total_supply_before
            // reserves_before[1].as_int(),
        )
        for index, result in enumerate(add_liquidity_result):
            add_liquidity_result[index] = result.as_int()
        self.assertEqual(
            [transferred_amount_zneo, transferred_amount_zgas_quoted, liquidity],
            add_liquidity_result,
        )

        transfer_events = []
        sync_events = []
        mint_events = []
        for event in notifications:
            if event.contract == self.contract_hash:
                if event.event_name == "Transfer":
                    transfer_events.append(event)
                elif event.event_name == "Sync":
                    sync_events.append(event)
                elif event.event_name == "Mint":
                    mint_events.append(event)

        self.assertEqual(1, len(transfer_events))
        self.assertEqual(3, len(transfer_events[0].state.as_list()))
        sender, receiver, amount = transfer_events[0].state.as_list()
        self.assertEqual(None, sender.as_none())
        self.assertEqual(self.user.script_hash, receiver.as_uint160())
        self.assertEqual(liquidity, amount.as_int())

        self.assertEqual(1, len(sync_events))
        self.assertEqual(2, len(sync_events[0].state.as_list()))
        balance_zneo, balance_zgas = sync_events[0].state.as_list()
        self.assertEqual(
            reserves_before[0].as_int() + transferred_amount_zneo, balance_zneo.as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() + transferred_amount_zgas_quoted,
            balance_zgas.as_int(),
        )

        self.assertEqual(1, len(mint_events))
        self.assertEqual(3, len(mint_events[0].state.as_list()))
        address, amount_zneo, amount_zgas = mint_events[0].state.as_list()
        self.assertEqual(self.user.script_hash, address.as_uint160())
        self.assertEqual(transferred_amount_zneo, amount_zneo.as_int())
        self.assertEqual(transferred_amount_zgas_quoted, amount_zgas.as_int())

    async def test_08_remove_liquidity(self):
        zgas_decimals = 10**8
        test_balance_zneo = 10_000_000
        test_balance_zgas = 10_000_000 * zgas_decimals
        transferred_amount_zneo = 10
        transferred_amount_zgas = 110 * zgas_decimals

        await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )

        # can't remove liquidity, because the user doesn't have any
        with self.assertRaises(AssertException) as context:
            await self.call(
                "remove_liquidity",
                [10000, 0, 0, self.owner.script_hash],
                return_type=list,
                signing_accounts=[self.owner],
            )
        self.assertEqual("not enough liquidity", str(context.exception))

        transfer_neo, _ = await self.transfer(
            NEO,
            self.genesis.script_hash,
            self.user.script_hash,
            test_balance_zneo,
        )
        transfer_gas, _ = await self.transfer(
            GAS,
            self.genesis.script_hash,
            self.user.script_hash,
            test_balance_zgas // zgas_decimals,
        )
        self.assertTrue(transfer_neo)
        self.assertTrue(transfer_gas)

        # minting zNEO to user
        transfer_zneo, _ = await self.transfer(
            NEO,
            self.user.script_hash,
            self.zneo_contract_hash,
            test_balance_zneo,
            signing_account=self.user,
        )
        # minting zGAS to user
        transfer_zgas, _ = await self.transfer(
            GAS,
            self.user.script_hash,
            self.zgas_contract_hash,
            test_balance_zgas // zgas_decimals,
            signing_account=self.user,
        )
        self.assertTrue(transfer_zneo)
        self.assertTrue(transfer_zgas)

        # approving the AMM contract, so that it will be able to transfer zNEO from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zneo],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zneo_contract_hash,
        )
        # approving the AMM contract, so that it will be able to transfer zGAS from user
        approve_zgas, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zgas],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zgas_contract_hash,
        )

        # adding liquidity to the pool will give you AMM tokens in return
        add_liquidity_result, _ = await self.call(
            "add_liquidity",
            [
                transferred_amount_zneo,
                transferred_amount_zgas,
                0,
                0,
                self.user.script_hash,
            ],
            return_type=list,
            signing_accounts=[self.user],
        )

        liquidity = int(math.sqrt(transferred_amount_zneo * transferred_amount_zgas))

        # saving data to demonstrate that the value will change later
        total_supply_before, _ = await self.call("totalSupply", return_type=int)
        balance_user_amm_before, _ = await self.call(
            "balanceOf", [self.user.script_hash], return_type=int
        )
        reserves_before, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        # removing liquidity from the pool will return the equivalent zNEO and zGAS that were used to fund the pool
        remove_liquidity, notifications = await self.call(
            "remove_liquidity",
            [liquidity, 0, 0, self.user.script_hash],
            return_type=list,
            signing_accounts=[self.user],
        )

        zneo_refunded = liquidity * balance_amm_zneo_before // total_supply_before
        zgas_refunded = liquidity * balance_amm_zgas_before // total_supply_before
        self.assertEqual(zneo_refunded, remove_liquidity[0].as_int())
        self.assertEqual(zgas_refunded, remove_liquidity[1].as_int())

        # data that will be compared with the previously saved data
        total_supply_after, _ = await self.call("totalSupply", return_type=int)
        balance_user_amm_after, _ = await self.call(
            "balanceOf", [self.user.script_hash], return_type=int
        )
        reserves_after, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        transfer_events = []
        sync_events = []
        burn_events = []
        for event in notifications:
            if event.contract == self.contract_hash:
                if event.event_name == "Transfer":
                    transfer_events.append(event)
                elif event.event_name == "Sync":
                    sync_events.append(event)
                elif event.event_name == "Burn":
                    burn_events.append(event)

        self.assertEqual(1, len(transfer_events))
        self.assertEqual(3, len(transfer_events[0].state.as_list()))
        sender, receiver, amount = transfer_events[0].state.as_list()
        self.assertEqual(self.user.script_hash, sender.as_uint160())
        self.assertEqual(None, receiver.as_none())
        self.assertEqual(liquidity, amount.as_int())

        self.assertEqual(1, len(sync_events))
        self.assertEqual(2, len(sync_events[0].state.as_list()))
        balance_zneo, balance_zgas = sync_events[0].state.as_list()
        self.assertEqual(
            reserves_before[0].as_int() - zneo_refunded, balance_zneo.as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() - zgas_refunded, balance_zgas.as_int()
        )

        self.assertEqual(1, len(burn_events))
        self.assertEqual(3, len(burn_events[0].state.as_list()))
        address, amount_zneo, amount_zgas = burn_events[0].state.as_list()
        self.assertEqual(self.user.script_hash, address.as_uint160())
        self.assertEqual(zneo_refunded, amount_zneo.as_int())
        self.assertEqual(zgas_refunded, amount_zgas.as_int())

        self.assertEqual(total_supply_before - liquidity, total_supply_after)
        self.assertEqual(balance_user_amm_before - liquidity, balance_user_amm_after)
        self.assertEqual(
            reserves_before[0].as_int() - zneo_refunded, reserves_after[0].as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() - zgas_refunded, reserves_after[1].as_int()
        )
        self.assertEqual(
            balance_user_zneo_before + zneo_refunded, balance_user_zneo_after
        )
        self.assertEqual(
            balance_user_zgas_before + zgas_refunded, balance_user_zgas_after
        )
        self.assertEqual(reserves_before[0].as_int(), balance_amm_zneo_before)
        self.assertEqual(reserves_before[1].as_int(), balance_amm_zgas_before)
        self.assertEqual(reserves_after[0].as_int(), balance_amm_zneo_after)
        self.assertEqual(reserves_after[1].as_int(), balance_amm_zgas_after)

    async def test_09_swap_zneo_to_zgas(self):
        zgas_decimals = 10**8
        test_balance_zneo = 10_000_000
        test_balance_zgas = 10_000_000 * zgas_decimals
        transferred_amount_zneo = 10
        transferred_amount_zgas = 110 * zgas_decimals

        await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )

        transfer_neo, _ = await self.transfer(
            NEO,
            self.genesis.script_hash,
            self.user.script_hash,
            test_balance_zneo,
        )
        transfer_gas, _ = await self.transfer(
            GAS,
            self.genesis.script_hash,
            self.user.script_hash,
            test_balance_zgas // zgas_decimals,
        )
        self.assertTrue(transfer_neo)
        self.assertTrue(transfer_gas)
        # minting zNEO to user
        transfer_zneo, _ = await self.transfer(
            NEO,
            self.user.script_hash,
            self.zneo_contract_hash,
            test_balance_zneo,
            signing_account=self.user,
        )
        # minting zGAS to user
        transfer_zgas, _ = await self.transfer(
            GAS,
            self.user.script_hash,
            self.zgas_contract_hash,
            test_balance_zgas // zgas_decimals,
            signing_account=self.user,
        )
        self.assertTrue(transfer_zneo)
        self.assertTrue(transfer_zgas)

        # approving the AMM contract, so that it will be able to transfer zNEO from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zneo],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zneo_contract_hash,
        )
        # approving the AMM contract, so that it will be able to transfer zGAS from user
        approve_zgas, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zgas],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zgas_contract_hash,
        )

        # adding liquidity to the pool will give you AMM tokens in return
        add_liquidity, _ = await self.call(
            "add_liquidity",
            [
                transferred_amount_zneo,
                transferred_amount_zgas,
                0,
                0,
                self.user.script_hash,
            ],
            return_type=list,
            signing_accounts=[self.user],
        )

        swapped_zneo = 1

        # won't work, because user did not have enough zNEO tokens
        with self.assertRaises(AssertException) as context:
            await self.call(
                "swap_tokens",
                [swapped_zneo, 0, self.zneo_contract_hash, self.user.script_hash],
                return_type=list,
                signing_accounts=[self.user],
            )
        self.assertEqual("insufficient allowance", str(context.exception))

        # approving the AMM contract, so that it will be able to transfer zNEO from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, swapped_zneo],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zneo_contract_hash,
        )
        self.assertTrue(approve_zneo)

        # saving data to demonstrate that the value will change later
        total_supply_before, _ = await self.call("totalSupply", return_type=int)
        reserves_before, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        swap_tokens, notifications = await self.call(
            "swap_tokens",
            [swapped_zneo, 0, self.zneo_contract_hash, self.user.script_hash],
            return_type=int,
            signing_accounts=[self.user],
        )

        # there is a 0.3% fee when doing a swap
        swapped_zneo_with_fee = swapped_zneo * (1000 - 3)
        swapped_zgas = (
            swapped_zneo_with_fee
            * reserves_before[1].as_int()
            // (reserves_before[0].as_int() * 1000 + swapped_zneo_with_fee)
        )
        self.assertEqual(swapped_zgas, swap_tokens)

        # data that will be compared with the previously saved data
        total_supply_after, _ = await self.call("totalSupply", return_type=int)
        reserves_after, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        swap_events = []
        for event in notifications:
            if event.contract == self.contract_hash:
                if event.event_name == "Swap":
                    swap_events.append(event)

        self.assertEqual(1, len(swap_events))
        self.assertEqual(5, len(swap_events[0].state.as_list()))
        (
            address,
            amount_zneo_in,
            amount_zgas_in,
            amount_zneo_out,
            amount_zgas_out,
        ) = swap_events[0].state.as_list()
        self.assertEqual(self.user.script_hash, address.as_uint160())
        self.assertEqual(swapped_zneo, amount_zneo_in.as_int())
        self.assertEqual(0, amount_zgas_in.as_int())
        self.assertEqual(0, amount_zneo_out.as_int())
        self.assertEqual(swapped_zgas, amount_zgas_out.as_int())

        self.assertEqual(total_supply_before, total_supply_after)
        self.assertEqual(
            reserves_before[0].as_int() + swapped_zneo, reserves_after[0].as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() - swapped_zgas, reserves_after[1].as_int()
        )
        self.assertEqual(
            balance_user_zneo_before - swapped_zneo, balance_user_zneo_after
        )
        self.assertEqual(
            balance_user_zgas_before + swapped_zgas, balance_user_zgas_after
        )
        self.assertEqual(reserves_before[0].as_int(), balance_amm_zneo_before)
        self.assertEqual(reserves_before[1].as_int(), balance_amm_zgas_before)
        self.assertEqual(reserves_after[0].as_int(), balance_amm_zneo_after)
        self.assertEqual(reserves_after[1].as_int(), balance_amm_zgas_after)
        self.assertEqual(
            reserves_before[0].as_int() + swapped_zneo, reserves_after[0].as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() - swapped_zgas, reserves_after[1].as_int()
        )

    async def test_10_swap_zgas_to_zneo(self):
        zgas_decimals = 10**8
        test_balance_zneo = 10_000_000
        test_balance_zgas = 10_000_000 * zgas_decimals
        transferred_amount_zneo = 100
        transferred_amount_zgas = 110 * zgas_decimals

        set_address = await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )
        self.assertTrue(set_address)
        transfer_neo, _ = await self.transfer(
            NEO,
            self.genesis.script_hash,
            self.user.script_hash,
            test_balance_zneo,
        )
        transfer_gas, _ = await self.transfer(
            GAS,
            self.genesis.script_hash,
            self.user.script_hash,
            test_balance_zgas // zgas_decimals,
        )
        self.assertTrue(transfer_neo)
        self.assertTrue(transfer_gas)
        # minting zNEO to user
        transfer_zneo, _ = await self.transfer(
            NEO,
            self.user.script_hash,
            self.zneo_contract_hash,
            test_balance_zneo,
            signing_account=self.user,
        )
        # minting zGAS to user
        transfer_zgas, _ = await self.transfer(
            GAS,
            self.user.script_hash,
            self.zgas_contract_hash,
            test_balance_zgas // zgas_decimals,
            signing_account=self.user,
        )
        self.assertTrue(transfer_zneo)
        self.assertTrue(transfer_zgas)
        # approving the AMM contract, so that it will be able to transfer zNEO from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zneo],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zneo_contract_hash,
        )
        # approving the AMM contract, so that it will be able to transfer zGAS from user
        approve_zgas, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, transferred_amount_zgas],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zgas_contract_hash,
        )

        # adding liquidity to the pool will give you AMM tokens in return
        add_liquidity, _ = await self.call(
            "add_liquidity",
            [
                transferred_amount_zneo,
                transferred_amount_zgas,
                0,
                0,
                self.user.script_hash,
            ],
            return_type=list,
            signing_accounts=[self.user],
        )

        swapped_zgas = 11 * 10**8

        # won't work, because user did not have enough zGAS tokens
        with self.assertRaises(AssertException) as context:
            await self.call(
                "swap_tokens",
                [swapped_zgas, 0, self.zgas_contract_hash, self.user.script_hash],
                return_type=list,
                signing_accounts=[self.user],
            )
        self.assertEqual("insufficient allowance", str(context.exception))

        # approving the AMM contract, so that it will be able to transfer zGAS from user
        approve_zneo, _ = await self.call(
            "approve",
            [self.user.script_hash, self.contract_hash, swapped_zgas],
            return_type=bool,
            signing_accounts=[self.user],
            target_contract=self.zgas_contract_hash,
        )
        self.assertTrue(approve_zneo)

        # saving data to demonstrate that the value will change later
        total_supply_before, _ = await self.call("totalSupply", return_type=int)
        reserves_before, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_before, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_before, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        # swapping zgas for zneo
        swap_tokens, notifications = await self.call(
            "swap_tokens",
            [swapped_zgas, 0, self.zgas_contract_hash, self.user.script_hash],
            return_type=int,
            signing_accounts=[self.user],
        )

        # there is a 0.3% fee when doing a swap
        swapped_zgas_with_fee = swapped_zgas * (1000 - 3)
        swapped_zneo = (
            swapped_zgas_with_fee
            * reserves_before[0].as_int()
            // (reserves_before[1].as_int() * 1000 + swapped_zgas_with_fee)
        )
        self.assertEqual(swapped_zneo, swap_tokens)

        # data that will be compared with the previously saved data
        total_supply_after, _ = await self.call("totalSupply", return_type=int)
        reserves_after, _ = await self.call("get_reserves", return_type=list)
        balance_user_zneo_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_user_zgas_after, _ = await self.call(
            "balanceOf",
            [self.user.script_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )
        balance_amm_zneo_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zneo_contract_hash,
        )
        balance_amm_zgas_after, _ = await self.call(
            "balanceOf",
            [self.contract_hash],
            return_type=int,
            target_contract=self.zgas_contract_hash,
        )

        swap_events = []
        for event in notifications:
            if event.contract == self.contract_hash:
                if event.event_name == "Swap":
                    swap_events.append(event)

        self.assertEqual(1, len(swap_events))
        self.assertEqual(5, len(swap_events[0].state.as_list()))
        (
            address,
            amount_zneo_in,
            amount_zgas_in,
            amount_zneo_out,
            amount_zgas_out,
        ) = swap_events[0].state.as_list()
        self.assertEqual(self.user.script_hash, address.as_uint160())
        self.assertEqual(0, amount_zneo_in.as_int())
        self.assertEqual(swapped_zgas, amount_zgas_in.as_int())
        self.assertEqual(swapped_zneo, amount_zneo_out.as_int())
        self.assertEqual(0, amount_zgas_out.as_int())

        self.assertEqual(total_supply_before, total_supply_after)
        self.assertEqual(
            reserves_before[0].as_int() - swapped_zneo, reserves_after[0].as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() + swapped_zgas, reserves_after[1].as_int()
        )
        self.assertEqual(
            balance_user_zneo_before + swapped_zneo, balance_user_zneo_after
        )
        self.assertEqual(
            balance_user_zgas_before - swapped_zgas, balance_user_zgas_after
        )
        self.assertEqual(reserves_before[0].as_int(), balance_amm_zneo_before)
        self.assertEqual(reserves_before[1].as_int(), balance_amm_zgas_before)
        self.assertEqual(reserves_after[0].as_int(), balance_amm_zneo_after)
        self.assertEqual(reserves_after[1].as_int(), balance_amm_zgas_after)
        self.assertEqual(
            reserves_before[0].as_int() - swapped_zneo, reserves_after[0].as_int()
        )
        self.assertEqual(
            reserves_before[1].as_int() + swapped_zgas, reserves_after[1].as_int()
        )

    async def test_11_on_nep17_payment(self):
        transferred_amount = 10
        await self.call(
            "set_address",
            [self.zneo_contract_hash, self.zgas_contract_hash],
            return_type=bool,
            signing_accounts=[self.owner],
        )
        # adding the transferred_amount into user
        t, _ = await self.transfer(
            NEO,
            self.genesis.script_hash,
            self.user.script_hash,
            transferred_amount,
        )
        self.assertTrue(t)
        t, _ = await self.transfer(
            NEO,
            self.user.script_hash,
            self.zneo_contract_hash,
            transferred_amount,
            signing_account=self.user,
        )
        self.assertTrue(t)

        # the AMM will accept this transaction, but there is no reason to send tokens directly to the smart contract.
        # to send tokens to the AMM you should use the add_liquidity function
        transfer_success, _ = await self.transfer(
            self.zneo_contract_hash,
            self.user.script_hash,
            self.contract_hash,
            transferred_amount,
            self.user,
        )
        self.assertTrue(transfer_success)

        # the smart contract will abort if some address other than zNEO or zGAS calls the onPayment method
        with self.assertRaises(AbortException) as context:
            await self.call(
                "onNEP17Payment",
                [self.user.script_hash, transferred_amount, None],
                return_type=bool,
            )
        self.assertEqual(
            "Invalid token. Only zNEO or zGAS are accepted", str(context.exception)
        )
