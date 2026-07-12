// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./MockAMM.sol";

/// @title MockRouter — multi-pool backrun arbitrage sandbox (Anvil only)
contract MockRouter {
    MockAMM public poolA;
    MockAMM public poolB;

    constructor(MockAMM a, MockAMM b) {
        poolA = a;
        poolB = b;
        a.setSandboxRouter(address(this));
        b.setSandboxRouter(address(this));
    }

    /// @notice Backrun: buy on poolB, mint on poolA, sell after victim moved poolA price
    function backrunArb(uint256 ethIn, uint256 minProfitWei) external payable returns (uint256 profit) {
        require(msg.value >= ethIn, "fund");
        uint256 start = address(this).balance;

        poolB.swapETHForTokens{value: ethIn}(0);
        uint256 tokens = poolB.balanceOf(address(this));
        require(tokens > 0, "no tokens");
        poolB.sandboxBurnBalance(address(this), tokens);
        poolA.sandboxMintBalance(address(this), tokens);
        poolA.swapTokensForETH(tokens, 0);

        uint256 end = address(this).balance;
        require(end >= start + minProfitWei, "no profit");
        profit = end - start;
        payable(msg.sender).transfer(profit);
    }

    receive() external payable {}
}
