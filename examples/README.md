# A statement you can try it on

```
crossfoot audit examples/statement.csv
```

Six months, 63 rows, and **entirely invented** — no real person, account,
merchant or amount is in it. It exists because the alternative first step was
"export your own bank statement", and nobody hands their bank data to a tool
they found five minutes ago. Try it on this, then decide.

Planted in it, because each one exercises a different behaviour:

| in the file | what it shows |
|---|---|
| a card terminal run twice, same merchant, same day | the finding that needs no receipt at all |
| a subscription that goes from 8.99 to 11.99 in April | a price rise, with the annual difference |
| a subscription that starts in March | a new recurring charge |
| a duplicate that was **refunded** five days later | suppressed to 0.00 at risk — the money came back |
| a subscription whose reference changes every month | one subscription, not six new ones |
| a running balance that steps correctly | the completeness check having something true to verify |

Change one balance and run it again: the audit will refuse to report anything
at all, because a duplicate found in a statement with rows missing is an
artefact of the gap, not a finding.
