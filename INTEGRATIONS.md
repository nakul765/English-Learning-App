# Optional future integrations

## Multi-user cloud sync
The current release is static HTML/CSS/JavaScript and saves each learner's data in their own browser LocalStorage. It can be hosted and opened by many people at once, but accounts and progress are not shared between devices.

For shared accounts, add Supabase (or Firebase):
1. Create an authentication project.
2. Create tables for `profiles`, `learning_progress`, `quiz_attempts`, `notebook_entries`, `verb_progress`, and `theme_inventory`.
3. Enable Row Level Security (RLS) and restrict every row to `auth.uid() = user_id`.
4. Add the public project URL and anon key to a separate config file. Never put a service-role key in frontend code.
5. Add sign-in/sign-up and sync LocalStorage changes to the signed-in user's rows.

Suggested `learning_progress` columns: `user_id`, `xp`, `coins`, `level`, `unlocked_themes` (JSON), `active_theme`, `updated_at`.
Suggested `notebook_entries` columns: `id`, `user_id`, `title`, `kind`, `content`, `created_at`, `updated_at`.

## AI writing evaluation
The current checker is local JavaScript and deliberately reports itself as a limited rule-based check. For reliable AI feedback:
1. Create a small backend endpoint (for example, a serverless function).
2. Store the AI provider API key only as a server-side secret.
3. Send the learner's essay and selected rubric to that endpoint.
4. Return corrections, explanations, and a suggested rewrite.
5. Ask the learner's permission before sending their writing to an external service.

Do not place a private AI API key in `upgrade.js` or any other browser file.
