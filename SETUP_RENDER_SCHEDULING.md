# Render Free Tier Scheduling Setup

Your Flask app is now configured to work with external scheduling for free hosting! This solves the problem where Render goes to sleep and breaks your background jobs.

## What We've Implemented

✅ **Secure task endpoints** (`/tasks/run`) that can be triggered externally  
✅ **GitHub Actions workflow** that runs even when Render sleeps  
✅ **Freshness checks** to ensure data is never stale when users visit  
✅ **Configurable scheduling** - you can enable/disable background threads  

## Setup Steps

### 1. Render Environment Variables

In your **Render dashboard** → **Environment** tab, add:

```
CRON_TOKEN=your_very_long_random_string_here_123456789
USE_EXTERNAL_SCHEDULING=true
```

**Generate a strong CRON_TOKEN:**
```bash
# Use any of these methods:
openssl rand -hex 32
# or
python -c "import secrets; print(secrets.token_hex(32))"
# or just create a long random string manually
```

### 2. GitHub Repository Secrets

In your **GitHub repo** → **Settings** → **Secrets and variables** → **Actions**:

Add these secrets:
- `CRON_TOKEN` = same token as in Render
- `TASK_URL` = `https://your-app-name.onrender.com/tasks/run`

### 3. Push Code to GitHub

Make sure both `tasks.py` and `.github/workflows/cron.yml` are in your repo:

```bash
git add .
git commit -m "Add external scheduling for Render free tier"
git push
```

### 4. Test the Setup

**Manual test:**
- Go to GitHub → Actions → "Scheduled Background Tasks" 
- Click "Run workflow" to test manually

**Check if it's working:**
- Monitor your Render logs for external task completion messages
- Check that your app gets the scheduled pings even when it was sleeping

## How It Works

### Your Current Jobs → External Schedule

| Job | Old Interval | New Schedule |
|-----|-------------|--------------|
| Price updates | Every 15 min | `*/15 * * * *` (every 15 min) |
| Historical data | Every 15 min | `5,20,35,50 * * * *` (offset by 5 min) |
| Weekly data | Every 6 hours | `1 0,6,12,18 * * *` (00:01, 06:01, etc.) |
| Monthly data | Every 12 hours | `2 0,12 * * *` (00:02, 12:02) |
| Daily cleanup | Daily | `55 23 * * *` (23:55 UTC) |

### Freshness Guarantees

When users visit your app, it automatically checks if data is stale (>20 minutes old) and triggers updates if needed. So even if external scheduling fails, users get fresh data.

## Testing Commands

Test individual jobs with curl:

```bash
# Test price updates
curl -X POST -H "Authorization: Bearer YOUR_CRON_TOKEN" \
  "https://your-app.onrender.com/tasks/run?t=15m-prices"

# Test historical collection  
curl -X POST -H "Authorization: Bearer YOUR_CRON_TOKEN" \
  "https://your-app.onrender.com/tasks/run?t=15m-historical"
```

## Free Tier Limits

- GitHub Actions: 2,000 minutes/month (way more than you need)
- Render: 750 hours/month (scheduled pings keep you under this)
- Your 15-minute pings = ~3,000 requests/month (well within limits)

## Monitoring

**Check Render logs** for messages like:
- `✅ External price update job completed`
- `✅ External historical collection job completed`

**Check GitHub Actions** → "Actions" tab for workflow runs.

## Rollback

To go back to internal scheduling, just set:
```
USE_EXTERNAL_SCHEDULING=false
```

## Benefits

✅ **No more broken jobs** when Render sleeps  
✅ **Perfect timing** - GitHub Actions runs on UTC schedule  
✅ **Free** - uses free tiers of both services  
✅ **Reliable** - GitHub's infrastructure is rock solid  
✅ **Fresh data** - automatic staleness detection when users visit  

Your background data collection will now work perfectly on Render's free tier! 🚀