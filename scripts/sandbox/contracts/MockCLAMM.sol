// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title MockCLAMM — concentrated-liquidity style pool for JIT MEV sandbox (Anvil only)
contract MockCLAMM {
    uint24 public constant FEE_BPS = 30; // 0.30% swap fee

    uint128 public totalLiquidity;
    uint256 public reserveETH;
    uint256 public reserveToken;

    uint256 public feeGrowthGlobalX128; // scaled fee per liquidity unit

    mapping(address => uint128) public liquidityOf;
    mapping(address => uint256) public feeGrowthInsideLastX128;

    event JITAdd(address indexed lp, uint128 liquidity, uint256 ethDeposited);
    event JITRemove(address indexed lp, uint128 liquidity, uint256 feesCollected, uint256 ethReturned);
    event Swap(address indexed trader, uint256 amountIn, uint256 amountOut, uint256 fee);

    constructor() payable {
        reserveETH = msg.value;
    }

    /// @notice JIT step 1 — add narrow liquidity position (single-block)
    function addLiquidityJIT(uint128 liquidity) external payable returns (uint256) {
        require(msg.value > 0 && liquidity > 0, "jit");
        _accrueFees(msg.sender);
        liquidityOf[msg.sender] += liquidity;
        totalLiquidity += liquidity;
        reserveETH += msg.value;
        reserveToken += uint256(liquidity);
        feeGrowthInsideLastX128[msg.sender] = feeGrowthGlobalX128;
        emit JITAdd(msg.sender, liquidity, msg.value);
        return msg.value;
    }

    /// @notice Victim / any trader swap (generates fees to active LPs)
    function swapETHForToken(uint256 minOut) external payable returns (uint256 out) {
        require(msg.value > 0, "no eth");
        uint256 fee = (msg.value * FEE_BPS) / 10_000;
        _distributeFee(fee);
        uint256 netIn = msg.value - fee;
        out = _amountOut(netIn, reserveETH, reserveToken);
        require(out >= minOut, "slippage");
        reserveETH += netIn;
        reserveToken -= out;
        emit Swap(msg.sender, msg.value, out, fee);
    }

    /// @notice JIT step 3 — remove liquidity + collect fee share
    function removeLiquidityJIT(uint128 liquidity) external returns (uint256 fees, uint256 ethOut) {
        require(liquidityOf[msg.sender] >= liquidity && liquidity > 0, "liq");
        fees = _accrueFees(msg.sender);
        uint256 tokenShare = (reserveToken * uint256(liquidity)) / uint256(totalLiquidity);
        ethOut = (reserveETH * uint256(liquidity)) / uint256(totalLiquidity);

        liquidityOf[msg.sender] -= liquidity;
        totalLiquidity -= liquidity;
        reserveETH -= ethOut;
        reserveToken -= tokenShare;

        payable(msg.sender).transfer(ethOut + fees);
        emit JITRemove(msg.sender, liquidity, fees, ethOut);
    }

    function pendingFees(address lp) external view returns (uint256) {
        uint128 liq = liquidityOf[lp];
        if (liq == 0) return 0;
        uint256 growth = feeGrowthGlobalX128 - feeGrowthInsideLastX128[lp];
        return (uint256(liq) * growth) / 1e18;
    }

    function _accrueFees(address lp) internal returns (uint256 fees) {
        uint128 liq = liquidityOf[lp];
        if (liq == 0) return 0;
        uint256 growth = feeGrowthGlobalX128 - feeGrowthInsideLastX128[lp];
        fees = (uint256(liq) * growth) / 1e18;
        feeGrowthInsideLastX128[lp] = feeGrowthGlobalX128;
    }

    function _distributeFee(uint256 fee) internal {
        if (totalLiquidity == 0 || fee == 0) return;
        feeGrowthGlobalX128 += (fee * 1e18) / uint256(totalLiquidity);
    }

    function _amountOut(uint256 amountIn, uint256 reserveIn, uint256 reserveOut)
        internal
        pure
        returns (uint256)
    {
        if (amountIn == 0 || reserveIn == 0 || reserveOut == 0) return 0;
        uint256 num = amountIn * reserveOut;
        uint256 den = reserveIn + amountIn;
        return num / den;
    }

    receive() external payable {
        reserveETH += msg.value;
    }
}
