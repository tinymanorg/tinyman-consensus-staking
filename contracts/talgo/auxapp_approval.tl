#pragma version 10
#tealish version git+https://github.com/Hipo/tealish.git@f1c2b72aaeb586ed082c380a638ed2e7ca47bcae

# Tinyman tAlgo
# License: https://github.com/tinymanorg/tinyman-consensus-staking/blob/main/LICENSE
# Documentation: https://docs.tinyman.org

# This app executes once and is deleted upon completion.
# Its only purpose is to rekey the application account to the creator.

inner_txn:
    TypeEnum: Pay
    Receiver: Txn.Sender
    RekeyTo: Txn.Sender
    Fee: 0
end
exit(1)
