# Browser Checkout

Use this route for a purchase through a product page. Follow Purchasing Flow for preparation, missing item choices, payment setup, and final confirmation. Use Payments & Wallet for wallet operations.

Call `browser.spawn_task` with a self-contained assignment:

```json
{
  "task": "Prepare the purchase of <items and exact product URLs>. Follow these requirements: <the user's requirements>. Use these supplied details: <name, delivery address, contact details, item variants and quantities>. Follow Purchasing Flow and report the proposed purchase and any remaining setup requirements. Wait for the user's confirmation before submitting."
}
```

Include any payment choice, Link refusal, or technical failure already established for this purchase. Keep card details out of the initial task. Follow the spawn tool's acknowledgment and asynchronous delivery instructions. Resolve payment setup when the browser returns the purchase review. Continue the same task with `browser.steer_task` as directed by Purchasing Flow.

For multiple purchases, run browser tasks in parallel only on different sites. Two checkouts on one site share the same cart.
