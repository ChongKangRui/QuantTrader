# Pip values (broker table, quote currency per lot size)

1 pip = 10 points (pipettes). Our engine uses points everywhere
(1 point = 1 tick on 5/3-digit quotes). Measured currency is always USD:
USD-quoted pairs read straight off the table; USD-base pairs divide by price;
quote-foreign pairs need a second feed (not supported yet).

| Pair | per 1.0 lot | per 0.1 | per 0.01 |
|---|---|---|---|
| AUDCAD | 10 CAD | 1 CAD | 0.10 CAD |
| AUDCHF | 10 CHF | 1 CHF | 0.10 CHF |
| AUDJPY | 1000 JPY | 100 JPY | 10 JPY |
| AUDNZD | 10 NZD | 1 NZD | 0.10 NZD |
| AUDSGD | 10 SGD | 1 SGD | 0.10 SGD |
| AUDUSD | 10 USD | 1 USD | 0.10 USD |
| CADCHF | 10 CHF | 1 CHF | 0.10 CHF |
| CADJPY | 1000 JPY | 100 JPY | 10 JPY |
| CHFJPY | 1000 JPY | 100 JPY | 10 JPY |
| CHFSGD | 10 SGD | 1 SGD | 0.10 SGD |
| EURAUD | 10 AUD | 1 AUD | 0.10 AUD |
| EURCAD | 10 CAD | 1 CAD | 0.10 CAD |
| EURCHF | 10 CHF | 1 CHF | 0.10 CHF |
| EURCZK | 10 CZK | 1 CZK | 0.10 CZK |
| EURGBP | 10 GBP | 1 GBP | 0.10 GBP |
| EURJPY | 1000 JPY | 100 JPY | 10 JPY |
| EURNOK | 10 NOK | 1 NOK | 0.10 NOK |
| EURNZD | 10 NZD | 1 NZD | 0.10 NZD |
| EURPLN | 10 PLN | 1 PLN | 0.10 PLN |
| EURSEK | 10 SEK | 1 SEK | 0.10 SEK |
| EURSGD | 10 SGD | 1 SGD | 0.10 SGD |
| EURTRY | 10 TRY | 1 TRY | 0.10 TRY |
| EURUSD | 10 USD | 1 USD | 0.10 USD |
| EURZAR | 10 ZAR | 1 ZAR | 0.10 ZAR |
| GBPAUD | 10 AUD | 1 AUD | 0.10 AUD |
| GBPCAD | 10 CAD | 1 CAD | 0.10 CAD |
| GBPCHF | 10 CHF | 1 CHF | 0.10 CHF |
| GBPJPY | 1000 JPY | 100 JPY | 10 JPY |
| GBPNOK | 10 NOK | 1 NOK | 0.10 NOK |
| GBPNZD | 10 NZD | 1 NZD | 0.10 NZD |
| GBPSEK | 10 SEK | 1 SEK | 0.10 SEK |
| GBPSGD | 10 SGD | 1 SGD | 0.10 SGD |
| GBPTRY | 10 TRY | 1 TRY | 0.10 TRY |
| GBPUSD | 10 USD | 1 USD | 0.10 USD |
| NOKJPY | 1000 JPY | 100 JPY | 10 JPY |
| NOKSEK | 10 SEK | 1 SEK | 0.10 SEK |
| NZDCAD | 10 CAD | 1 CAD | 0.10 CAD |
| NZDCHF | 10 CHF | 1 CHF | 0.10 CHF |
| NZDJPY | 1000 JPY | 100 JPY | 10 JPY |
| NZDUSD | 10 USD | 1 USD | 0.10 USD |
| SEKJPY | 1000 JPY | 100 JPY | 10 JPY |
| SGDJPY | 10000 JPY | 100 JPY | 10 JPY |
| USDCAD | 10 CAD | 1 CAD | 0.10 CAD |
| USDCHF | 10 CHF | 1 CHF | 0.10 CHF |
| USDCNH | 10 CNH | 1 CNH | 0.10 CNH |
| USDCZK | 10 CZK | 1 CZK | 0.10 CZK |
| USDJPY | 1000 JPY | 100 JPY | 10 JPY |
| USDMXN | 10 MXN | 1 MXN | 0.10 MXN |
| USDNOK | 10 NOK | 1 NOK | 0.10 NOK |
| USDPLN | 10 PLN | 1 PLN | 0.10 PLN |
| USDSEK | 10 SEK | 1 SEK | 0.10 SEK |
| USDSGD | 10 SGD | 1 SGD | 0.10 SGD |
| USDTHB | 10 THB | 1 THB | 0.10 THB |
| USDTRY | 10 TRY | 1 TRY | 0.10 TRY |
| USDZAR | 10 ZAR | 1 ZAR | 0.10 ZAR |
| ZARJPY | 1000 JPY | 1 JPY | 10 JPY |

Worked check (0.01 lot): 300 points = 30 pips = 30 x $0.10 = **$3.00** on EURUSD.
