from algosdk import transaction
from algosdk.encoding import decode_address, encode_address
from .base_client import BaseClient


class TAlgoClient(BaseClient):

    def init(self):
        sp = self.get_suggested_params()
        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                receiver=self.application_address,
                sp=sp,
                amt=10_000_000,
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["init"],
                accounts=[],
                foreign_assets=[]
            ),
        ]
        return self._submit(transactions, additional_fees=13)
    
    def sync(self):
        sp = self.get_suggested_params()
        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["sync"],
                accounts=[
                    encode_address(self.get_global(b"account_1")),
                    encode_address(self.get_global(b"account_2")),
                    encode_address(self.get_global(b"account_3")),
                    encode_address(self.get_global(b"account_4")),
                ],
                foreign_assets=[]
            ),
        ]
        return self._submit(transactions, additional_fees=0)

    def mint(self, amount):
        sp = self.get_suggested_params()
        transactions = [
            self.get_optin_if_needed_txn(self.user_address, self.get_global(b"talgo_asset_id")),
            transaction.PaymentTxn(
                sender=self.user_address,
                receiver=self.application_address,
                sp=sp,
                amt=amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["mint", amount],
                accounts=[
                    encode_address(self.get_global(b"account_1")),
                    encode_address(self.get_global(b"account_2")),
                    encode_address(self.get_global(b"account_3")),
                    encode_address(self.get_global(b"account_4")),
                ],
                foreign_assets=[
                    self.get_global(b"talgo_asset_id"),
                ]
            ),
        ]
        return self._submit(transactions, additional_fees=4)
    
    def burn(self, amount):
        sp = self.get_suggested_params()
        transactions = [
            transaction.AssetTransferTxn(
                sender=self.user_address,
                receiver=self.application_address,
                sp=sp,
                amt=amount,
                index=self.get_global(b"talgo_asset_id")
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["burn", amount],
                accounts=[
                    encode_address(self.get_global(b"account_1")),
                    encode_address(self.get_global(b"account_2")),
                    encode_address(self.get_global(b"account_3")),
                    encode_address(self.get_global(b"account_4")),
                ],
                foreign_assets=[
                ]
            ),
        ]
        return self._submit(transactions, additional_fees=1)
