#pragma version 10

assert(Txn.ApplicationID == 0)
inner_txn:
    TypeEnum: Pay
    Receiver: Txn.Sender
    RekeyTo: Txn.Sender
    Fee: 0
end
exit(1)
