// The browser's IANA timezone, sent with every API request so the backend can
// resolve "today" in the user's calendar instead of the container's UTC clock.
// Detection is best-effort: when it fails we send nothing and the documented
// server fallback (UTC) applies. Never send a date from here — the server owns
// the clock, this only says where the user is.

export const TIMEZONE_HEADER = 'X-User-Timezone';

export const deviceTimezone = () => {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch {
        return '';
    }
};

const DEVICE_TIMEZONE = deviceTimezone();

// Spread into a headers object; a falsy zone adds no header at all.
export const timezoneHeader = () => (DEVICE_TIMEZONE ? { [TIMEZONE_HEADER]: DEVICE_TIMEZONE } : {});
