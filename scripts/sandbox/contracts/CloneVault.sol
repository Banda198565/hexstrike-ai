// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Implementation for EIP-1167 clones — initialize once per clone.
contract CloneVault {
    address public owner;
    uint256 public balance;

    /// @dev Called once after clone deploy (implementation constructor NOT re-run).
    function initialize(address _owner) external {
        require(owner == address(0), "already init");
        owner = _owner;
    }

    function deposit() external payable {
        balance += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(msg.sender == owner, "not owner");
        require(balance >= amount, "insufficient");
        balance -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }
}
