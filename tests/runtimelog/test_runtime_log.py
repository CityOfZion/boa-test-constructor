import asyncio
from boaconstructor import SmartContractTestCase
from neo3.wallet import account


class RuntimeLogTest(SmartContractTestCase):
    genesis: account.Account

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        asyncio.run(cls.asyncSetupClass())

    @classmethod
    async def asyncSetupClass(cls) -> None:
        cls.genesis = cls.node.wallet.account_get_by_label("committee")  # type: ignore
        cls.contract_hash = await cls.deploy("resources/runtimelog_contract.nef", cls.genesis)

    async def test_main1(self):
        msg = "msg1"
        await self.call("main", [msg], return_type=None)
        self.assertEqual(1, len(self.runtime_logs))
        self.assertEqual(self.contract_hash, self.runtime_logs[0].contract)
        self.assertEqual(msg, self.runtime_logs[0].msg)

    async def test_main2(self):
        msg = "msg2"
        await self.call("main", [msg], return_type=None)
        self.assertEqual(1, len(self.runtime_logs))
        self.assertEqual(msg, self.runtime_logs[0].msg)
