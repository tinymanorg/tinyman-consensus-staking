#pragma version 10

# This app executes once and is deleted upon completion.
# Its only purpose is to rekey the application account to the creator.

inner_txn:
    TypeEnum: Pay
    Receiver: Txn.Sender
    RekeyTo: Txn.Sender
    Fee: 0
end
exit(1)
