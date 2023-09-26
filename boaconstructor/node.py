import pathlib
import threading
import subprocess
import shlex
import logging
import sys
import time
import yaml

import abc
from neo3.wallet import wallet, account
from neo3.api.wrappers import ChainFacade

log = logging.getLogger("neogo")
log.addHandler(logging.StreamHandler(sys.stdout))


class Node(abc.ABC):
    wallet: wallet.Wallet
    account_committee: account.Account
    facade: ChainFacade

    @classmethod
    @abc.abstractmethod
    def start(cls):
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def stop(cls):
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def reset(cls):
        raise NotImplementedError


class NeoGoNode(Node):
    def __init__(self, config_path: str):
        self.config_path = str(pathlib.Path(config_path).absolute())
        self._process = None
        self._ready = False
        self.thread = None
        self._parse_config()

    def start(self):
        log.debug("starting")
        # TODO: change this to resolve from the included resources in the distributed package
        # probably have to use something like https://docs.python.org/3.10/library/importlib.html#module-importlib.resources
        # right now it will resolve from test file location
        cmd = f"../../scripts/neogo node --config-file {self.config_path}"

        self._process = subprocess.Popen(
            shlex.split(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            shell=False,
        )

        def process_stdout(process):
            for output in iter(process.stdout.readline, b""):
                if "RPC server already started" in output:
                    self._ready = True
                    break

        self.thread = threading.Thread(target=process_stdout, args=(self._process,))
        self.thread.start()

        while not self._ready:
            time.sleep(0.0001)
        log.debug("running")

    def stop(self):
        log.debug("stopping")
        if self._process is not None:
            self._process.kill()
            self._process.wait()
        log.debug("stopped")

    @classmethod
    def reset(cls):
        # neo-go uses an in memory database so there's no need to reset anything
        pass

    def _parse_config(self):
        with open(self.config_path) as f:
            config: dict = list(yaml.load_all(f, yaml.FullLoader))[0]
            data = config["ApplicationConfiguration"]

            # TODO: the config file defines the path as relative to where neogo was ran from, this 'parent.parent' assumes project root
            # which does not have to be the case. Make resilient
            consensus_wallet_path = (
                pathlib.Path(self.config_path).parent.parent
                / data["Consensus"]["UnlockWallet"]["Path"]
            )
            consensus_wallet_password = data["Consensus"]["UnlockWallet"]["Password"]
            tmp_wallet = wallet.Wallet.from_file(
                str(consensus_wallet_path.absolute()),
                passwords=[
                    consensus_wallet_password,
                    consensus_wallet_password,
                ],
            )
            priv_key = account.Account.private_key_from_nep2(
                tmp_wallet.account_default.encrypted_key,
                consensus_wallet_password,
                _scrypt_parameters=tmp_wallet.scrypt,
            )
            acc = account.Account.from_private_key(
                priv_key, "123", scrypt_parameters=tmp_wallet.scrypt
            )
            acc.label = "committee-signature"
            self.wallet = wallet.Wallet(scrypt_params=tmp_wallet.scrypt)
            self.wallet.account_add(acc, is_default=True)

            self.account_committee = self.wallet.import_multisig_address(
                1, [self.wallet.account_default.public_key]
            )
            self.account_committee.label = "committee"

            # TODO: warn if port is :0 because then we can't tell where the RPC server is running on
            address = data["RPC"]["Addresses"][0]
            host = f"http://{address}"
            self.facade = ChainFacade(rpc_host=host)
