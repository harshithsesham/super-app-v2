# Shopify UCP Checkout

Load this file only after the user has selected one or more Meta catalog
products from the same merchant whose `is_agentic_checkout_creation_enabled`
fields are all exactly `true`.

The catalog flags route the flow; the checkout endpoint remains authoritative.
Use every selected product's exact `product_id`, capability fields, and `url`
from its catalog data. Bundle products only when their catalog URLs clearly
identify the same merchant storefront; matching brand labels are not enough.
Never mix merchants in one checkout. Treat a missing or null capability as
`false`.

## Safety and input boundary

- `checkout create` moves no money. `checkout complete` creates the Stripe Link
  spend request and places the order.
- `checkout complete` serves the Stripe Link lane only. Native completion
  addresses the merchant's card handler, so Shop Pay is reachable only in the
  browser. The browser task places a Shop Pay order. Do not call `checkout
  complete` for it.
- Run `checkout complete` at most once for a checkout and only in the
  foreground. Never create a Stripe Link spend request separately, background
  completion, poll it, or retry it automatically.
- A denial is the user's decision. Stop without placing an order. A later retry
  requires a new explicit user message.
- CLI inputs are JSON files with snake_case keys. Omit unknown optional fields
  and empty strings. Never carry endpoint-derived merchant, item, total, buyer,
  fulfillment, or legal-link data into completion input.

## Cart (optional)

A pre-purchase draft, never required — `checkout create` takes `items[]`
directly. Reach for one only when the basket must survive the turn: the user is
still adding or removing, or wants to come back to it later.
`shopify-ucp-cli cart --help` covers the subcommands; carry the `cart_id` from
`agent_state.cart_id` and treat it as opaque. Four things --help does not tell
you:

- `cart update` replaces the whole basket — that is how an item is removed, and
  why a partial list deletes the rest. Unsure you have every item? `cart get`
  first and rebuild from `cart.line_items[]`.
- One cart, one merchant. A cart spanning two is refused outright:
  `multiple_merchants_not_supported`, "All cart line items must belong to the
  same merchant." Start a separate cart rather than retrying.
- `cart` accepts a catalog `product_id` or the variant GID it echoes back;
  `checkout create` accepts catalog ids only. A resumed cart can be revised but
  not checked out until you search again for its catalog ids.
- Nothing links a cart to a checkout: it supplies items only. Cancel it once
  `checkout complete` returns `ok: true`, or once the browser task reports the
  order placed on the Shop Pay lane; nothing else closes it, and there is no
  way to enumerate the ones you left open.
- Cart, checkout, and order reads preserve provider timestamps and add semantic
  UTC and user-local forms such as `checkout_expires_at`, `order_placed_at`,
  and `order_event_occurred_at`. Do not treat an order-status message time as a
  delivery time.

## Create the checkout

Confirm every product, exact variant, and quantity, then gather any required
buyer detail you do not already know. Never guess, fabricate, or leave a
required field blank. Checkout creation moves no money; save final purchase
approval for the completed quote.

Creation needs no payment method. Do not resolve Link, connect a wallet, or ask
about payment before this call. The user picks the payment lane after the
checkout exists, under *Choose the payment lane* below.

Create one JSON file containing every selected product. Use each catalog
`product_id` as `items[].item_id`; use one entry per distinct variant and fold
repeated identical IDs into its quantity. Quantity defaults to `1`. Do not add
a merchant field: the endpoint resolves the merchant from the catalog IDs. The
endpoint requires buyer email and USD. Include phone and address fields only
when known. Native completion additionally requires a trusted cardholder first
or last name and billing/shipping address with street, city, state, postal code,
and ISO alpha-2 country.

`checkout update` changes the delivery selection alone, so a name and address
missing at creation cannot be added later. Gather them before this call
whenever every selected product's `is_agentic_checkout_completion_enabled` is
exactly `true`. Take what you already know from the conversation and
`~/USER.md`. Ask for the rest in one message covering name, full address,
email, and phone, following the one-request rule in Purchasing Flow. Phone is
optional to the create endpoint and routinely required by the merchant's own
delivery step, so ask for it here with the rest. Then wait for the answer.

Skip that ask when any selected product's
`is_agentic_checkout_completion_enabled` is not exactly `true`, and skip it
when the user has already chosen Shop Pay. The browser collects the address
itself in both cases.

```json
{
  "buyer": {
    "email": "<email>",
    "phone_number": "<phone-string>",
    "country_code": "<country-code>",
    "address": {
      "first_name": "<first-name>",
      "last_name": "<last-name>",
      "street1": "<street1>",
      "street2": "<street2>",
      "city": "<city>",
      "state": "<state>",
      "postal_code": "<postal-code>",
      "country": "<country-alpha-2>"
    }
  },
  "items": [
    {"item_id": "<product_id-1>", "quantity": 1},
    {"item_id": "<product_id-2>", "quantity": 2}
  ],
  "currency": "USD"
}
```

```sh
shopify-ucp-cli checkout create --input-file "<checkout.json>" --format json
```

Put the complete item set in this initial create call. `checkout update` changes
only delivery selection; it cannot add or remove products. Do not use the
separate `cart` commands to assemble this checkout.

Inspect the authoritative create response before branching on the catalog completion capability. A returned `continue_url` does not by itself require a browser handoff because native-ready checkouts may also include one.

If create returns an error or rejects the item, explain the result and offer browser checkout from the original catalog `url`; do not retry automatically.

Only a successful create response with a usable `.agent_state.checkout_id` may continue below. Save that checkout ID. The CLI stores the endpoint-derived checkout behind the trusted runtime boundary. Inspect `.result` without copying its trusted fields into later commands.

A response carrying `requires_escalation`, `status: "redirect"`, or a note that
buyer detail is still missing is a successful create when it returned a
checkout ID. Do not treat it as an error. It does not say which lane's brief to
send, so ask the lane question before handing off.

Take the checkout URL now, from `.result.continue_url` or
`.result.checkout.continue_url`. Use only a value the endpoint returned. When
it is absent, fall back to one selected product's original catalog `url` from
that merchant rather than inventing one.

## Choose the payment lane

The checkout exists and moves no money yet. Ask the user which payment lane to
use, with `muse.create_options`. Wait for the answer before any wallet call or
browser handoff. Put nothing in that message that competes with the two options
for the answer, under the shopping skill's rule against stacking two questions
in one message. Follow Payments & Wallet for what the question says, including
the sentence that choosing Shop Pay sends the code.

- **Shop Pay**: the merchant's accelerated checkout, run in the browser. It
  sends a one-time code to the user's phone or email.
- **Stripe Link**: a one-time virtual card capped at the approved amount.

Ask this question before any other message that follows creation. Ask it even
when the create response reports `requires_escalation`, `status: "redirect"`, a
missing shipping address, no delivery options, or a total that is not final.
None of those says which lane the user wants. Do not offer to open the checkout
in the browser before the answer arrives, because that offer picks the lane. Do
not resolve Link before the answer arrives. Do not offer card details in chat
as a third option.

On escalation, redirect, or a name or address missing at creation, say
alongside the two options that the browser will finish this checkout and
collect what is missing. Missing delivery options and an unsettled total are
ordinary native work under *Refresh delivery and totals* below, so do not say
the browser will place the order for those.

When the user names some other payment method, continue with browser checkout
from the catalog `url` under `references/browser-checkout.md`, relaying the
Link decline in the brief.

A user who does not choose has declined nothing. Ask once more, naming the
difference that decides it: Shop Pay needs a code from their phone or email,
and Stripe Link does not. If they still do not choose, take the Stripe Link
lane and say which one you took. Do not read silence as choosing Shop Pay,
because only an explicit answer authorizes a code-gated lane. On that path,
send the brief's no-answer lane sentence, defined under *Stripe Link, in the
browser* below. Do not send the selection sentence. The no-answer sentence
reports that the user made no choice, so it claims no choice on their behalf.

## Route after creation

The Stripe Link lane covers both the user's own choice of Link and the lane you
took for them on the no-answer path above. Take the first branch that matches:

1. Shop Pay, which the user chose explicitly: the browser, whatever
   `is_agentic_checkout_completion_enabled` says.
2. The Stripe Link lane, and create reported `status: "redirect"`,
   `requires_escalation`, or messages that explicitly require buyer input or
   review: the browser, carrying Link. Take this branch regardless of
   `is_agentic_checkout_completion_enabled`.
3. The Stripe Link lane, and any selected product's
   `is_agentic_checkout_completion_enabled` is not exactly `true`: the browser,
   carrying Link.
4. The Stripe Link lane, and the checkout was created without the name and
   address native completion requires: the browser, carrying Link.

Otherwise every selected product's `is_agentic_checkout_completion_enabled` is
exactly `true`, and the native flow below applies.

On any browser branch, briefly acknowledge the handoff and end the response
after delegating. Do not poll the browser task. Do not call `checkout complete`
for that checkout.

### Shop Pay, in the browser

Spawn the task on the checkout URL. State in the instruction both that the user
selected Shop Pay and that they authorized sending its one-time code. A brief
carrying only the selection makes the browser seat stop and ask before touching
Shop Pay. Do not drop or soften either clause.

```json
{
  "task": "<what the user asked for, in their words>. Open <exact Shopify checkout URL> for <selected products>. The user selected Shop Pay for this purchase and authorized sending its one-time code. Stripe Link status for this checkout: the user declined Link. Pay with Shop Pay: prepare the purchase through final review, but do not submit or pay. Use these known choices for every item: <color/size/quantity/other variants>. Ask only for missing required purchase choices. Shop Pay will send the user a one-time code; ask the user for the code when the checkout reaches that step. If this checkout does not offer Shop Pay, stop and ask the user which payment method to use instead rather than substituting one. At final review, report the exact checkout terms and the Shop Pay method that will be charged. Shipping preference: <deadline/budget/speed, or none>."
}
```

Keep the Link status sentence: the browser seat's payment rules read it to
decide whether to offer Link at final review. Its wording matches the sibling
brief in `references/browser-checkout.md`.

Do not resolve Link, call any wallet tool, or raise Link with the user on this
lane. Treat the terms the browser reports at final review as authoritative,
because Shop Pay may supersede the buyer detail sent to `checkout create` with
the user's own saved card and address.

### Stripe Link, in the browser

Resolve Link first, following *Resolve Link* below, then spawn the task. The
brief carries one lane sentence, and the browser seat matches on its wording.
When the user answered the lane question, use: `The user selected Stripe Link
for this purchase.` When the user did not choose, use: `The user was asked to
choose a payment lane and did not choose, so Stripe Link was taken for them.`
Do not reword either sentence, and do not send both.

```json
{
  "task": "<what the user asked for, in their words>. Open <exact Shopify checkout URL> for <selected products>. <lane sentence> Stripe Link status for this checkout: <connected; or the exact technical Link failure>. Prepare the purchase through final review, but do not submit or pay. Use these known choices for every item: <color/size/quantity/other variants>. Ask only for missing required purchase choices. At final review, report the exact checkout terms and saved payment choices. Verify any selected Link method before payment. Shipping preference: <deadline/budget/speed, or none>."
}
```

### Stripe Link, completed natively

Resolve Link as below, then continue with the native flow.

## Resolve Link

On either Stripe Link route, resolve Link once the lane is settled, following
Payments & Wallet. Run that check after the user picks Link. Do not run it
before creating the checkout.

Until Link resolves on a native route, do not write completion input and do not
call `shopify-ucp-cli checkout complete`. If Link fails technically or the user
declines it, offer Shop Pay for this same checkout URL, or browser checkout
from the catalog `url`. Do not fall back to a lane the user has not chosen.

## Refresh delivery and totals

If the checkout offers delivery options, select one. With more than one, if the
user stated a shipping preference (a deadline, budget, or speed) or the options
are trivially close, pick the best fit and tell the user which you chose;
otherwise present the options with their price and delivery estimate and let the
user choose. Update the trusted quote before completion:

If the checkout requires independent delivery choices for different item
groups, do not attempt native completion; continue in the browser from the
returned checkout URL.

```json
{
  "checkout_id": "<checkout-id>",
  "selected_delivery_option_id": "<delivery-option-id>"
}
```

```sh
shopify-ucp-cli checkout update --input-file "<update.json>" --format json
```

Review the updated checkout and total. A checkout without delivery options
skips this step.

## Select payment and complete

Reuse the payment methods returned when you resolved Link for this purchase. Call
`wallet.list_payment_methods` again only when the user connected Link or added a
payment method after that list.

Native completion supports only entries whose `type` is exactly `card`. Ignore
bank accounts and other payment-method types. Use the default only when Link
explicitly marks a card as default; otherwise ask the user to choose among the
returned cards. If no card is available, do not attempt native completion;
offer to add one with `wallet.add_payment_method` or continue in the browser from the catalog URL.

The first time you name the card you are going to charge, say in the same
sentence that the user can use a different one. If the card they name is not in
Link, send the add page. When they come back, list once and go straight to the
quote. Do not re-confirm the switch they just asked for.

Show the completed quote with the masked method, items, final total, and
delivery choice, then ask for explicit approval. This quote is the purchase
review for a native completion, so follow Purchasing Flow for how it reads.
Link connection and an earlier request to buy are not approval for this quote.
After approval, write completion input containing only the trusted checkout ID,
chosen payment-method ID, and selected delivery-option ID when one exists:

```json
{
  "checkout_id": "<checkout-id>",
  "payment_method_id": "<stripe-link-payment-method-id>",
  "selected_delivery_option_id": "<delivery-option-id>"
}
```

Omit `selected_delivery_option_id` when the checkout has no delivery selection.

```sh
shopify-ucp-cli checkout complete --input-file "<complete.json>" --format json
```

Read the top-level `ok`: `true` means the order was placed; `false` means it was
not. Never paste raw `.result` JSON or expose internal IDs, API fields, buyer
contact information, or shipping-address details. Summarize only available
user-facing fields: order status, products, merchant, final amount, delivery
estimate, and confirmation link. If completion fails after card save or reports
an unknown outcome, do not claim no order was placed and do not retry or switch
to browser checkout automatically.
