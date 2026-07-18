// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "forge-std/Test.sol";
import "../RevertOnWithdraw.sol";

/// @notice Sandbox PoC: honeypot reverts when balance snapshot diverges (Playbook D).
contract RevertOnWithdrawHoneypotPoC is Test {
    RevertOnWithdraw public target;
    address user = address(0xCAFE);

    function setUp() public {
        target = new RevertOnWithdraw();
        vm.deal(address(target), 2 ether);
        vm.deal(user, 1 ether);
    }

    function test_withdraw_succeeds_when_balance_unchanged() public {
        target.snapshot();
        vm.prank(user);
        target.withdraw(payable(user), 0.5 ether);
        assertEq(user.balance, 1.5 ether);
    }

    function test_withdraw_reverts_when_balance_changes() public {
        target.snapshot();
        // Donation changes contract balance after snapshot — honeypot triggers.
        vm.deal(address(target), address(target).balance + 0.1 ether);
        vm.prank(user);
        vm.expectRevert(bytes("BLOCK"));
        target.withdraw(payable(user), 0.5 ether);
    }
}
