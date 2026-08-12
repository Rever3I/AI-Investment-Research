# Value Investing Stock Analysis Pro

Five stages from screening to sizing, built on the buy-side research process.
Financials come straight from SEC filings. It does not predict prices; it works
out what a business is worth and what the current price already assumes.

## What you get

| Stage | Output |
| --- | --- |
| Screen | A shortlist with a one-line reason each, from your criteria or from a view you hold |
| Research | A written thesis: business, management, competitors, TAM, 8-12 risks, and what would prove it wrong |
| Value | An owner-earnings DCF, a reverse DCF, and an interactive HTML page |
| Size | A position weight from your scenario probabilities, half-Kelly by default |
| Recheck | A diff against your original thesis when you are thinking about selling |

## A real run

Coca-Cola, using figures pulled live from SEC EDGAR:

```
Owner earnings   $12.0B      (net income + D&A - capex, FY2025 10-K)
Shares           4.31B       CommonStockSharesOutstanding
Price            $86.84      Yahoo, verified fresh

Reverse DCF      19.7%       the growth the price already assumes,
                             at a 9.2% discount rate and 2.6% terminal growth

Scenarios        bull $54.24   base $47.96   bear $40.61
Half-Kelly       0.00%       no edge at this price
```

The reverse DCF is the line to read first. It turns "is Coca-Cola cheap" into a
question you can actually answer: is a soft drinks company going to compound
owner earnings at 19.7% a year for a decade? The scenario values and the
position size follow from your own growth assumptions, not from the tool's.

Every figure above carries a source, a unit and an as-of date. Anything stale
stops the run rather than quietly ageing into the report.

## The interactive valuation page

Each valuation writes a single self-contained HTML file. Drag the discount rate
or terminal growth and every scenario recomputes in the browser. No CDN, no
fonts, no network calls, so it still opens years later on a machine with no
connection.

It shows the stored figures on first open and says so, then marks itself as
recomputed once you move something. A scenario that set its own discount rate
keeps it when you move the global one, so a bear case stays a bear case.

It also reports terminal share per scenario: how much of the value sits in the
perpetuity assumption rather than in the projected years. A valuation that is
85% terminal value is a statement about the discount rate more than about the
business, and you should be able to see that.

## Why the numbers can be trusted

Reading XBRL naively produces figures that look completely ordinary and are
wrong. These are real cases, found by running against live filings, and each is
now blocked by a rule:

| Company | Naive result | Actual | Cause |
| --- | --- | --- | --- |
| Simon Property | 1.30B shares | 324M | Weighted-average share counts are filed as period entries, so four quarters got summed |
| McDonald's | 716 shares | 708M | The count is filed in millions |
| Starbucks | D&A $362M | $1.77B | A fresher single quarter beat the annual figure, and the company then showed no owner earnings at all |
| Shell (London) | $3,356 | ~$45 | London quotes in pence, and the price was labelled as dollars |
| NVIDIA | Capex from 2020 | Current | The tag NVIDIA used until 2020 was still winning over the one it uses now |

None of these fails a sanity check. A summed share count is still a plausible
share count. A quarterly depreciation figure is still a plausible depreciation
figure. They can only be caught by rules: stock quantities are never summed,
periods are filtered by actual duration, prices must carry a currency, and a
figure past its age limit is refused.

## What it refuses to do

Refusing is a feature here. Each of these would otherwise produce a confident
number that means nothing.

- **Banks and REITs.** They often have no capital expenditure line, and owner
  earnings is net income plus depreciation less capex. A missing term reads as
  zero and flatters exactly the businesses where capex matters most. It says the
  method does not fit rather than filling the gap.
- **Loss-making companies.** An owner-earnings DCF on negative owner earnings
  returns a negative price target with an ordinary-looking terminal share hiding
  two negatives in a ratio.
- **One company in two currencies.** A yuan price against dollar financials is
  a valuation wrong by the exchange rate, and every digit of it looks ordinary.
  That combination hard-stops. A non-dollar listing on its own does not: yuan
  price against yuan financials is a correct valuation, and so is Hong Kong.
- **Listings quoted in a subunit.** London quotes in pence, so Shell comes back
  as 3356 against a real price near GBP 45. The currency label is right and only
  the unit is wrong, which is why no downstream check can see it.
- **Foreign private issuers.** They file under IFRS, which this does not read,
  and it says so instead of implying the ticker is wrong.
- **A position with no edge.** When expected return is not positive at the
  current price, Kelly sizes at zero. That is the arithmetic declining the bet,
  not a missing answer.

## Setup

Prices work with no configuration. Two optional keys unlock the rest:

```json
{
  "sec_contact": "Your Name you@example.com",
  "fred_api_key": "",
  "output_language": "en",
  "sizing_method": "half_kelly",
  "position_cap": 1.0
}
```

- `sec_contact` is required by the SEC in the User-Agent header. Without it
  EDGAR returns 403, so US financials have no source.
- `fred_api_key` is free from the St. Louis Fed and supplies the risk-free rate
  that gives a discount rate its provenance.
- `output_language` writes your research in any language you set. Log and error
  messages stay in English so a traceback is searchable.

Run `status_report(configure())` at any time to see which sources can run and
exactly which setting is missing.

## Data sources

| Domain | Source | Needs |
| --- | --- | --- |
| Quotes | Yahoo (two hosts), then Stooq | nothing |
| US financials | SEC EDGAR XBRL company facts | `sec_contact` |
| Macro | FRED | a free key |
| Chinese listings | Wind | a licensed terminal |

Each domain is a chain. When the first source fails the next is tried and the
fallback is recorded, because a primary that quietly always fails looks
identical to one that works until the fallback fails too.

## Use cases

**You saw a name on fintwit and want to know if it is interesting.** Screen or
go straight to research, then look at the reverse DCF. If the price already
assumes 40% growth for a decade, you have your answer without building a model.

**You have a macro view and no tickers.** Start from the view. Intake reasons
from the thesis outward to the companies that sit in that value chain.

**You are up 60% and wondering whether to trim.** Recheck pulls up what you
originally argued and sorts what changed into facts changed, judgment changed,
or still holds. The three call for different responses and feel identical from
inside a winning position.

**You want to size a position you have already decided on.** Give it your
scenario probabilities and it returns half-Kelly with the inputs attached, so
the number can be argued with later.

## FAQ

**Does it tell me what to buy?**
No. It presents what the price assumes, what the numbers support, and what would
prove the thesis wrong. Every stage stops short of a recommendation.

**Does it predict prices?**
No. The reverse DCF reports the growth rate the current price implies, which is
a description of the market's assumption rather than a forecast.

**How current is the data?**
Annual figures come from the most recent 10-K, quarterly from filed quarters.
Prices are the last regular-session print. Anything past its staleness limit
hard-stops rather than being used.

**Can I use it for Chinese A-shares?**
The Wind adapter is written to Wind's documented interface but has not been
verified against a live terminal, because WindPy ships with the paid product and
cannot be installed otherwise. Treat it as a starting point.

**What if I disagree with the valuation?**
You should be able to. The growth rates and probabilities are yours, the
discount rate has no default and must be supplied with a source, and the
interactive page exists so you can move the assumptions and watch the answer
change.

**Does it need an internet connection?**
For fetching data, yes. The valuation pages it writes work offline afterwards.

## Limits worth knowing

- Owner-earnings DCF suits profitable businesses with identifiable capital
  expenditure. It is a poor fit for banks, insurers, early-stage companies and
  many REITs, and it says so rather than producing a number.
- The Wind adapter is unverified against a live terminal.
- Nothing here is investment advice.
