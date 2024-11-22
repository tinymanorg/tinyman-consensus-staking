# Tinyman Liquid Staking

This repo contains the contracts that form the Tinyman Liquid Staking system.

### Docs

The liquid staking system is described in detail in the following document:
[Tinyman Liquid Staking Specification](docs/Tinyman_Liquid_Staking_Protocol_Specification.pdf)

User docs for Tinyman Liquid Staking can be found at [docs.tinyman.org](https://docs.tinyman.org).


### Contracts
The contracts are written in [Tealish](https://github.com/tinymanorg/tealish).
The specific version of Tealish is https://github.com/tinymanorg/tealish/tree/f1c2b72aaeb586ed082c380a638ed2e7ca47bcae.

The annotated TEAL outputs and compiled bytecode are available in the build subfolders.


### Audits

Audit reports from independent reviewers can be found in the [audits](audits/) directory.


### Security
#### Reporting a Vulnerability
Reports of potential flaws must be responsibly disclosed to security@tinyman.org. Do not share details with anyone else until notified to do so by the team.


### Installing Dependencies
Note: Mac OS & Linux Only

```
% python3 -m venv ~/envs/talgo
% source ~/envs/talgo/bin/activate
(talgo) % pip install -r requirements.txt
(talgo) % python -m algojig.check
```

We recommend using VS Code with this Tealish extension when reviewing contracts written in Tealish: https://github.com/thencc/TealishVSCLangServer/blob/main/tealish-language-server-1.0.0.vsix


### Running Tests

```
# Run all tests (this can take a while)
(talgo) % python -m unittest -v

# Run a specific test
(talgo) % python -m unittest -vk "tests.tests_talgo.TestSetup.test_create_app"
```

Note: The tests read the `.tl` Tealish source files from the contracts directories, not the `.teal` build files.


### Compiling the Contract Sources

```
# Compile each set of contracts to generate the `.teal` files in the `build` subdirectories:
(talgo) % tealish compile contracts/talgo
(talgo) % tealish compile contracts/talgo_staking
```

### Licensing

The contents of this repository are licensed under the Business Source License 1.1 (BUSL-1.1), see [LICENSE](LICENSE).
