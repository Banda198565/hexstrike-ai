// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title MockAMM — constant-product pool for offensive MEV sandbox (Anvil only)
contract MockAMM {
    uint256 public reserveETH;
    uint256 public reserveToken;
    mapping(address => uint256) public balanceOf;

    event Swap(address indexed trader, bool ethToToken, uint256 amountIn, uint256 amountOut);

    constructor() payable {
        reserveETH = msg.value;
        reserveToken = 1000 ether;
    }

    receive() external payable {
        reserveETH += msg.value;
    }

    function addLiquidity(uint256 tokenAmount) external payable {
        require(msg.value > 0 && tokenAmount > 0, "amounts");
        reserveETH += msg.value;
        reserveToken += tokenAmount;
    }

    function swapETHForTokens(uint256 minOut) external payable returns (uint256 out) {
        require(msg.value > 0, "no eth");
        out = _amountOut(msg.value, reserveETH, reserveToken);
        require(out >= minOut, "slippage");
        reserveETH += msg.value;
        reserveToken -= out;
        balanceOf[msg.sender] += out;
        emit Swap(msg.sender, true, msg.value, out);
    }

    function swapTokensForETH(uint256 tokenIn, uint256 minEthOut) external returns (uint256 out) {
        require(tokenIn > 0, "no tokens");
        require(balanceOf[msg.sender] >= tokenIn, "balance");
        out = _amountOut(tokenIn, reserveToken, reserveETH);
        require(out >= minEthOut, "slippage");
        balanceOf[msg.sender] -= tokenIn;
        reserveToken += tokenIn;
        reserveETH -= out;
        payable(msg.sender).transfer(out);
        emit Swap(msg.sender, false, tokenIn, out);
    }

    function _amountOut(uint256 amountIn, uint256 reserveIn, uint256 reserveOut)
        internal
        pure
        returns (uint256)
    {
        uint256 num = amountIn * reserveOut;
        uint256 den = reserveIn + amountIn;
        return num / den;
    }
}
