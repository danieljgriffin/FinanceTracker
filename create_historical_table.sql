-- Create historical net worth tracking table
CREATE TABLE IF NOT EXISTS historical_net_worth (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    net_worth DECIMAL(12, 2) NOT NULL,
    platform_breakdown JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for efficient time-based queries
CREATE INDEX IF NOT EXISTS idx_historical_net_worth_timestamp ON historical_net_worth(timestamp);

-- Create index for recent data queries
CREATE INDEX IF NOT EXISTS idx_historical_net_worth_created_at ON historical_net_worth(created_at);