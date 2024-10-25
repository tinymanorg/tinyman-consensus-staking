from algosdk import transaction
from algosdk.encoding import decode_address, encode_address
from .base_client import BaseClient


class TAlgoClient(BaseClient):

    keyreg_lsig = transaction.LogicSigAccount(b"\n\x81\x01C")

    def init(self):
        sp = self.get_suggested_params()
        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                receiver=self.application_address,
                sp=sp,
                amt=2_000_000,
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

    def go_online(self, node_index, vote_pk, selection_pk, state_proof_pk, vote_first, vote_last, vote_key_dilution, fee):
        account_address = encode_address(self.get_global(b"account_%i" % node_index))
        self.add_key(account_address, self.keyreg_lsig)
        sp = self.get_suggested_params()
        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                receiver=account_address,
                sp=sp,
                amt=fee
            ) if fee else None,
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["change_online_status", node_index],
                accounts=[
                ],
                foreign_assets=[
                ]
            ),
            transaction.KeyregOnlineTxn(
                sender=account_address,
                sp=sp,
                rekey_to=self.application_address,
                votekey=vote_pk,
                selkey=selection_pk,
                votefst=vote_first,
                votelst=vote_last,
                votekd=vote_key_dilution,
                sprfkey=state_proof_pk,
            )
        ]
        if fee:
            transactions[2].fee = fee
        return self._submit(transactions, additional_fees=1)
    
    def go_offline(self, node_index):
        account_address = encode_address(self.get_global(b"account_%i" % node_index))
        self.add_key(account_address, self.keyreg_lsig)
        sp = self.get_suggested_params()
        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["change_online_status", node_index],
                accounts=[
                ],
                foreign_assets=[
                ]
            ),
            transaction.KeyregOfflineTxn(
                sender=account_address,
                sp=sp,
                rekey_to=self.application_address,
            )
        ]
        return self._submit(transactions, additional_fees=1)

    def set_node_manager(self, node_index, node_manager_address):
        sp = self.get_suggested_params()
        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["set_node_manager", node_index, decode_address(node_manager_address)],
                accounts=[
                ],
                foreign_assets=[]
            ),
        ]
        return self._submit(transactions, additional_fees=0)
    

    def move_stake(self, from_node_index, to_node_index, amount):
        sp = self.get_suggested_params()
        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["move_stake", from_node_index, to_node_index, amount],
                accounts=[
                    encode_address(self.get_global(b"account_1")),
                    encode_address(self.get_global(b"account_2")),
                    encode_address(self.get_global(b"account_3")),
                    encode_address(self.get_global(b"account_4")),
                ],
                foreign_assets=[]
            ),
        ]
        return self._submit(transactions, additional_fees=1)
    
    def claim_protocol_rewards(self):
        sp = self.get_suggested_params()
        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["claim_protocol_rewards"],
                accounts=[
                   encode_address(self.get_global(b"fee_collector")),
                ],
                foreign_assets=[
                    self.get_global(b"talgo_asset_id"),
                ]
            ),
        ]
        return self._submit(transactions, additional_fees=1)