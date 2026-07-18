// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {CloneVault} from "./CloneVault.sol";

/// @notice Minimal EIP-1167 factory for local learning (testnet/anvil only).
contract MinimalCloneFactory {
    address public immutable implementation;

    event Cloned(address indexed user, address indexed clone);

    constructor() {
        implementation = address(new CloneVault());
    }

    /// @dev Deploy EIP-1167 minimal proxy pointing at `implementation`, then initialize.
    function cloneFor(address user) external returns (address clone) {
        clone = _clone(implementation);
        CloneVault(clone).initialize(user);
        emit Cloned(user, clone);
    }

    function _clone(address master) internal returns (address instance) {
        bytes20 targetBytes = bytes20(master);
        assembly {
            let clone := mload(0x40)
            mstore(
                clone,
                or(
                    0x363d3d373d3d3d363d730000000000000000000000000000000000000000,
                    shl(0x48, targetBytes)
                )
            )
            mstore(add(clone, 0x14), 0x5af43d82803e903d91602a57fd5bf300000000000000000000000000)
            instance := create(0, clone, 0x37)
        }
        require(instance != address(0), "clone failed");
    }
}
