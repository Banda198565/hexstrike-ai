// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Intentionally weak bank for orchestrator smoke tests (local analysis only).
contract Bank {
    mapping(address => uint256) public balances;
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    // Missing onlyOwner — anyone can withdraw any account balance.
    function withdraw(address from, uint256 amount) external {
        require(balances[from] >= amount, "insufficient");
        balances[from] -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }

    function setOwner(address newOwner) external {
        owner = newOwner;
    }
}
