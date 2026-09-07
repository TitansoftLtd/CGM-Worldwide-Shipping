---
title: Payroll & HR
metatags:
  description: HR admin stub — leave pointer, Additional Salary Tool, Kenya PAYE/NSSF/SHIF returns, and DTB Salary Payment Schedule.
---

# Payroll & HR

**Kenya payroll helpers and statutory reports for HR and Finance admins — not day-to-day leave filing.**

Use this short guide when you run payroll tools or monthly statutory returns. Employees applying for leave should open the Leave guide instead.

A typical scenario: HR posts additional salary components for a payroll period via **Additional Salary Tool**, then runs **PAYE Monthly Return**, **NSSF Monthly Return**, and **SHIF Monthly Return**, and exports **DTB Salary Payment Schedule** for bank upload.

To access HR tools, go to:

> Home > Human Resources

Also use CGM reports under Report / workspace links for PAYE, NSSF, SHIF, and DTB.

## 1. Prerequisites

- HR Manager / Payroll roles and report permissions
- Employees with salary structures and components configured in ERPNext
- Write permission on **Additional Salary Tool** when using that single

## 2. How to — Leave (employees)

Day-to-day leave application, balances, sick-leave documents, and approval chains:

→ **[Leave](leave.md)**

## 3. Features — Additional Salary Tool

**Additional Salary Tool** (single DocType) batches additional salary lines for a period:

- Select payroll period / employees / components per site process
- Creates or updates **Additional Salary** drafts for payroll
- Respects Role Permission Manager — grant write access deliberately

Use it instead of hand-entering many Additional Salary documents one by one.

## 4. Features — Kenya statutory reports

| Report | Audience |
|--------|----------|
| **PAYE Monthly Return** | Tax withholding return |
| **NSSF Monthly Return** | NSSF contributions |
| **SHIF Monthly Return** | SHIF contributions |
| **DTB Salary Payment Schedule** | Bank payment file / schedule for DTB |

Run after salary slips for the period are ready. Exact columns follow the report filters on your site.

## 5. Related Topics

- [Leave](leave.md)
- [Finance](finance.md)
- [Documentation Hub](../README.md)
