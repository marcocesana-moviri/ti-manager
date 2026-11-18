import React, { useState, useEffect, useRef, useMemo } from 'react';
import Button from '@splunk/react-ui/Button';
import Text from '@splunk/react-ui/Text';
import Table from '@splunk/react-ui/Table';
import Select from '@splunk/react-ui/Select';
import Paginator from '@splunk/react-ui/Paginator';
import Heading from '@splunk/react-ui/Heading';
import WaitSpinner from '@splunk/react-ui/WaitSpinner';
import Modal from '@splunk/react-ui/Modal';

import { defaultFetchInit } from '@splunk/splunk-utils/fetch';
import { StyledContainer, StyledGreeting } from './ManualAllowStyles';

const APP_NAME = 'moviri_ti_manager_app';
const COLLECTION_NAME = 'manual_allowlist';
const locale = window.location.pathname.split('/')[1] || 'en-US';
const KV_STORE_URL = `/${locale}/splunkd/__raw/servicesNS/nobody/${APP_NAME}/storage/collections/data/${COLLECTION_NAME}`;

type DurationUnit = 'm' | 'h' | 'd' | 'never';

interface IPRow {
    _key: string;
    ip: string;
    user: string;
    reason: string;
    timestamp: string;
    expirydate: string;
    source?: string;
}

interface FileListGroup {
    source: string;
    count: number;
    user: string;
    timestamp: string;
    keys: string[];
}

const splunkFetch = (url: string, options: RequestInit = {}) => {
    return fetch(url, {
        ...(defaultFetchInit as RequestInit),
        ...options,
        headers: {
            ...(defaultFetchInit as RequestInit).headers,
            ...options.headers,
        },
    });
};

const isValidCIDR = (cidr: string): boolean => {
    const octet = '(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])';
    const cidrRegex = new RegExp(
        `^${octet}\\.${octet}\\.${octet}\\.${octet}\\/([0-9]|[1-2][0-9]|3[0-2])$`,
    );
    return cidrRegex.test(cidr);
};

const parseAndNormalizeIps = (input: string): string[] => {
    const rawIps = input
        .split(/[\s,;]+/)
        .map((ip) => ip.trim())
        .filter((ip) => ip.length > 0)
        .map((ip) => (ip.includes('/') ? ip : `${ip}/32`));
    return Array.from(new Set(rawIps));
};

const normalizeKey = (cidr: string) => cidr.replace(/\//g, '_');

const formatTimestamp = (isoString?: string) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return isNaN(date.getTime()) ? '-' : date.toLocaleString();
};

const calculateExpiryDate = (val: string, unit: DurationUnit): string => {
    if (unit === 'never') return '';
    const now = new Date();
    const num = parseInt(val, 10) || 0;
    if (num <= 0) return '';
    if (unit === 'm') now.setMinutes(now.getMinutes() + num);
    if (unit === 'h') now.setHours(now.getHours() + num);
    if (unit === 'd') now.setDate(now.getDate() + num);
    return now.toISOString();
};

const ipToNumber = (cidr: string): number => {
    const [ip] = cidr.split('/');
    if (!ip) return 0;
    return ip.split('.').reduce((acc, octet) => (acc << 8) + parseInt(octet, 10), 0) >>> 0;
};

function useDebounce<T>(value: T, delay: number): T {
    const [debouncedValue, setDebouncedValue] = useState<T>(value);
    useEffect(() => {
        const handler = setTimeout(() => setDebouncedValue(value), delay);
        return () => clearTimeout(handler);
    }, [value, delay]);
    return debouncedValue;
}

const ManualAllow: React.FC = () => {
    const [ips, setIps] = useState<IPRow[]>([]);

    // Form States
    const [newIp, setNewIp] = useState<string>('');
    const [newUser, setNewUser] = useState<string>('');
    const [newReason, setNewReason] = useState<string>('');
    const [newDurationValue, setNewDurationValue] = useState<string>('24');
    const [newDurationUnit, setNewDurationUnit] = useState<DurationUnit>('h');

    // UI States
    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [isInitialLoad, setIsInitialLoad] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);
    const [successMsg, setSuccessMsg] = useState<string | null>(null);
    const [modalConfig, setModalConfig] = useState<{
        isOpen: boolean;
        title: string;
        message: string;
        onConfirm: () => void;
    } | null>(null);

    // Table States
    const [searchQuery, setSearchQuery] = useState<string>('');
    const debouncedSearchQuery = useDebounce(searchQuery, 300);
    const [currentPage, setCurrentPage] = useState<number>(1);
    const [pageSize, setPageSize] = useState<number>(10);
    const [sortState, setSortState] = useState<{
        key: keyof IPRow | 'none';
        dir: 'asc' | 'desc' | 'none';
    }>({ key: 'none', dir: 'none' });
    const [selectedKeys, setSelectedKeys] = useState<string[]>([]);

    const fileInputRef = useRef<HTMLInputElement>(null);
    const abortControllerRef = useRef<AbortController | null>(null);
    const modalReturnFocusRef = useRef<any>(null);

    useEffect(() => {
        const fetchCurrentUser = async () => {
            try {
                const res = await splunkFetch(
                    `/${locale}/splunkd/__raw/services/authentication/current-context?output_mode=json`,
                );
                if (res.ok) {
                    const data = await res.json();
                    const username = data?.entry?.[0]?.content?.username || 'Unknown';
                    setNewUser(username);
                }
            } catch (err) {
                console.error('Unable to get current user:', err);
            }
        };

        fetchCurrentUser();
        fetchIps();

        return () => {
            if (abortControllerRef.current) abortControllerRef.current.abort();
        };
    }, []);

    useEffect(() => {
        setCurrentPage(1);
        setSelectedKeys([]);
    }, [debouncedSearchQuery]);

    const showSuccess = (msg: string) => {
        setSuccessMsg(msg);
        setTimeout(() => setSuccessMsg(null), 5000);
    };

    const fetchIps = async () => {
        setIsLoading(true);
        setError(null);
        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();

        try {
            let allFetchedIps: IPRow[] = [];
            let currentSkip = 0;
            const CHUNK_LIMIT = 50000;
            let keepFetching = true;

            while (keepFetching) {
                const response = await splunkFetch(
                    `${KV_STORE_URL}?limit=${CHUNK_LIMIT}&skip=${currentSkip}`,
                    { signal: abortControllerRef.current.signal },
                );

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(
                        `Failed to fetch chunk at skip ${currentSkip} (${response.status}): ${errorText}`,
                    );
                }

                const chunk: IPRow[] = await response.json();
                allFetchedIps = [...allFetchedIps, ...chunk];

                if (chunk.length < CHUNK_LIMIT) keepFetching = false;
                else currentSkip += CHUNK_LIMIT;
            }
            setIps(allFetchedIps);
        } catch (err: unknown) {
            if (err instanceof Error && err.name === 'AbortError') return;
            setError(
                `Network error while fetching data: ${err instanceof Error ? err.message : String(err)}`,
            );
        } finally {
            setIsLoading(false);
            setIsInitialLoad(false);
        }
    };

    // --- KPI Computations (Single Pass & Memoized) ---
    const { totalActiveIps, permanentAllowsCount, averageDurationStr } = useMemo(() => {
        const now = Date.now();
        let activeCount = 0;
        let permanentCount = 0;
        let totalMs = 0;
        let timedCount = 0;

        ips.forEach((row) => {
            const isExpired = row.expirydate && new Date(row.expirydate).getTime() <= now;
            if (isExpired) return;

            activeCount++;
            if (!row.expirydate) {
                permanentCount++;
            } else if (row.timestamp) {
                const start = new Date(row.timestamp).getTime();
                const end = new Date(row.expirydate).getTime();
                if (!isNaN(start) && !isNaN(end) && end > start) {
                    totalMs += end - start;
                    timedCount++;
                }
            }
        });

        let avgStr = 'N/A';
        if (timedCount > 0) {
            const avgHours = totalMs / timedCount / (1000 * 60 * 60);
            if (avgHours < 1) avgStr = `${(avgHours * 60).toFixed(0)} Mins`;
            else if (avgHours > 24) avgStr = `${(avgHours / 24).toFixed(1)} Days`;
            else avgStr = `${avgHours.toFixed(1)} Hours`;
        }

        return {
            totalActiveIps: activeCount,
            permanentAllowsCount: permanentCount,
            averageDurationStr: avgStr,
        };
    }, [ips]);

    const fileLists = useMemo(() => {
        const groups: Record<string, FileListGroup> = {};
        ips.forEach((row) => {
            if (row.source) {
                if (!groups[row.source]) {
                    groups[row.source] = {
                        source: row.source,
                        count: 0,
                        user: row.user,
                        timestamp: row.timestamp,
                        keys: [],
                    };
                }
                groups[row.source].count += 1;
                groups[row.source].keys.push(row._key);
            }
        });
        return Object.values(groups).sort(
            (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        );
    }, [ips]);

    const filteredIps = useMemo(() => {
        const query = debouncedSearchQuery.toLowerCase();
        if (!query) return ips;
        return ips.filter(
            (row) =>
                row.ip.toLowerCase().includes(query) ||
                (row.user && row.user.toLowerCase().includes(query)) ||
                (row.reason && row.reason.toLowerCase().includes(query)) ||
                (row.source && row.source.toLowerCase().includes(query)),
        );
    }, [ips, debouncedSearchQuery]);

    const sortedIps = useMemo(() => {
        const { key, dir } = sortState;
        if (dir === 'none' || key === 'none') return filteredIps;

        return [...filteredIps].sort((a, b) => {
            if (key === 'ip') {
                const numA = ipToNumber(a.ip);
                const numB = ipToNumber(b.ip);
                return dir === 'asc' ? numA - numB : numB - numA;
            }

            if (key === 'expirydate') {
                const timeA = a.expirydate ? new Date(a.expirydate).getTime() : Infinity;
                const timeB = b.expirydate ? new Date(b.expirydate).getTime() : Infinity;
                return dir === 'asc' ? timeA - timeB : timeB - timeA;
            }

            const valA = (a[key] || '').toLowerCase();
            const valB = (b[key] || '').toLowerCase();
            if (valA < valB) return dir === 'asc' ? -1 : 1;
            if (valA > valB) return dir === 'asc' ? 1 : -1;
            return 0;
        });
    }, [filteredIps, sortState]);

    const totalPages = Math.max(1, Math.ceil(sortedIps.length / pageSize));
    const paginatedIps = useMemo(
        () => sortedIps.slice((currentPage - 1) * pageSize, currentPage * pageSize),
        [sortedIps, currentPage, pageSize],
    );

    const selectedKeysSet = useMemo(() => new Set(selectedKeys), [selectedKeys]);
    const allPageSelected =
        paginatedIps.length > 0 && paginatedIps.every((row) => selectedKeysSet.has(row._key));

    const handleToggleAll = () => {
        const pageKeys = paginatedIps.map((row) => row._key);
        if (allPageSelected) {
            setSelectedKeys((prev) => prev.filter((k) => !pageKeys.includes(k)));
        } else {
            const newKeys = new Set([...selectedKeys, ...pageKeys]);
            setSelectedKeys(Array.from(newKeys));
        }
    };

    const handleToggleRow = (key: string) => {
        setSelectedKeys((prev) =>
            prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
        );
    };

    const handleSort = (e: any, { sortKey: newSortKey }: any) => {
        setSortState((prev) => {
            if (prev.key === newSortKey) {
                const nextDir = prev.dir === 'asc' ? 'desc' : prev.dir === 'desc' ? 'none' : 'asc';
                return {
                    key: nextDir === 'none' ? 'none' : (newSortKey as keyof IPRow),
                    dir: nextDir,
                };
            }
            return { key: newSortKey as keyof IPRow, dir: 'asc' };
        });
    };

    const existingIpsSet = useMemo(() => new Set(ips.map((row) => row.ip)), [ips]);
    const ipsToAdd = useMemo(() => parseAndNormalizeIps(newIp), [newIp]);

    const isInputEmpty = ipsToAdd.length === 0;
    const isTooMany = ipsToAdd.length > 20;
    const isFormatValid = isInputEmpty || ipsToAdd.every(isValidCIDR);
    const isDuplicate = ipsToAdd.some((ip) => existingIpsSet.has(ip));
    const isDurationValid =
        newDurationUnit === 'never' ||
        (!isNaN(Number(newDurationValue)) && Number(newDurationValue) > 0);

    const isAddBtnDisabled =
        isInputEmpty || !isFormatValid || isDuplicate || isTooMany || !isDurationValid || isLoading;
    const isBulkBtnDisabled = isLoading || !isDurationValid;

    const handleAddIp = async (e?: React.FormEvent) => {
        if (e) e.preventDefault();
        if (isAddBtnDisabled) return;

        setError(null);
        setIsLoading(true);
        const nowIso = new Date().toISOString();
        const expiryIso = calculateExpiryDate(newDurationValue, newDurationUnit);

        const payload = ipsToAdd.map((ip) => ({
            _key: normalizeKey(ip),
            ip: ip,
            user: newUser.trim() || 'Unknown',
            reason: newReason.trim() || 'No reason provided',
            timestamp: nowIso,
            expirydate: expiryIso,
        }));

        try {
            if (payload.length === 1) {
                const response = await splunkFetch(KV_STORE_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload[0]),
                });
                if (!response.ok) throw new Error(await response.text());
            } else {
                const response = await splunkFetch(`${KV_STORE_URL}/batch_save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!response.ok) throw new Error(await response.text());
            }

            setNewIp('');
            setNewReason('');
            showSuccess(`Successfully added ${payload.length} IP(s).`);
            await fetchIps();
        } catch (err: unknown) {
            setError(
                `Network error while saving: ${err instanceof Error ? err.message : String(err)}`,
            );
        } finally {
            setIsLoading(false);
        }
    };

    const performBatchDelete = async (keysToRemove: string[]) => {
        let hasErrors = false;
        const CHUNK_SIZE = 100;

        const chunks = [];
        for (let i = 0; i < keysToRemove.length; i += CHUNK_SIZE) {
            chunks.push(keysToRemove.slice(i, i + CHUNK_SIZE));
        }

        const deletePromises = chunks.map(async (keysChunk) => {
            const queryJson = JSON.stringify({ _key: { $in: keysChunk } });
            try {
                const response = await splunkFetch(
                    `${KV_STORE_URL}?query=${encodeURIComponent(queryJson)}`,
                    { method: 'DELETE' },
                );
                if (!response.ok) {
                    hasErrors = true;
                    console.error('Failed to batch delete chunk', await response.text());
                }
            } catch (err) {
                hasErrors = true;
                console.error('Network error on batch delete', err);
            }
        });

        await Promise.all(deletePromises);
        return hasErrors;
    };

    const confirmBulkRemove = () => {
        setModalConfig({
            isOpen: true,
            title: 'Confirm Bulk Deletion',
            message: `Are you sure you want to remove ${selectedKeys.length} selected IPs? This action cannot be undone.`,
            onConfirm: async () => {
                setModalConfig(null);
                if (selectedKeys.length === 0) return;
                setError(null);
                setIsLoading(true);

                const hasErrors = await performBatchDelete(selectedKeys);
                if (hasErrors)
                    setError(
                        'Some selected items could not be deleted successfully. Check console logs.',
                    );
                else showSuccess(`Successfully deleted ${selectedKeys.length} IPs.`);

                setSelectedKeys([]);
                await fetchIps();
            },
        });
    };

    const confirmRemoveList = (keysToRemove: string[], listName: string) => {
        setModalConfig({
            isOpen: true,
            title: 'Confirm List Removal',
            message: `Are you sure you want to remove all ${keysToRemove.length} IPs associated with the list "${listName}"?`,
            onConfirm: async () => {
                setModalConfig(null);
                if (keysToRemove.length === 0) return;
                setError(null);
                setIsLoading(true);

                const hasErrors = await performBatchDelete(keysToRemove);
                if (hasErrors)
                    setError(
                        'Some items from the list could not be deleted successfully. Check console logs.',
                    );
                else showSuccess(`Successfully removed list "${listName}".`);

                setSelectedKeys((prev) => prev.filter((k) => !keysToRemove.includes(k)));
                await fetchIps();
            },
        });
    };

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const fileName = file.name;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const text = e.target?.result as string;
            if (text) await processBulkIps(text, fileName);
            if (fileInputRef.current) fileInputRef.current.value = '';
        };
        reader.readAsText(file);
    };

    const processBulkIps = async (text: string, fileName: string) => {
        setError(null);
        setIsLoading(true);

        const lines = text
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter((line) => line.length > 0);

        if (lines.length === 0) {
            setError('The selected file is empty or contains no valid data.');
            setIsLoading(false);
            return;
        }

        const now = new Date().toISOString();
        const expiryIso = calculateExpiryDate(newDurationValue, newDurationUnit);

        const seenInFile = new Set<string>();
        const uniqueParsedData = [];
        let invalidCount = 0;
        let firstInvalid = '';

        for (const line of lines) {
            const [rawIp = '', rawUser = '', ...reasonParts] = line.split(',');
            const rawIpTrim = rawIp.trim();
            const ip = rawIpTrim.includes('/') ? rawIpTrim : `${rawIpTrim}/32`;

            if (!isValidCIDR(ip)) {
                invalidCount++;
                if (!firstInvalid) firstInvalid = ip;
                continue;
            }

            if (!existingIpsSet.has(ip) && !seenInFile.has(ip)) {
                const user = rawUser.trim() || newUser.trim() || 'Unknown';
                const reason = reasonParts.join(',').trim() || newReason.trim() || 'Bulk upload';

                uniqueParsedData.push({
                    _key: normalizeKey(ip),
                    ip: ip,
                    user,
                    reason,
                    timestamp: now,
                    expirydate: expiryIso,
                    source: fileName,
                });
                seenInFile.add(ip);
            }
        }

        if (invalidCount > 0) {
            setError(
                `Upload blocked: Found ${invalidCount} invalid CIDR formats (e.g., "${firstInvalid}"). Ensure file format is IP,User,Reason.`,
            );
            setIsLoading(false);
            return;
        }

        if (uniqueParsedData.length === 0) {
            setError(
                'All the IPs in this file are already present in the allowlist. No new IPs were added.',
            );
            setIsLoading(false);
            return;
        }

        const CHUNK_SIZE = 1000;
        let hasErrors = false;

        for (let i = 0; i < uniqueParsedData.length; i += CHUNK_SIZE) {
            const chunk = uniqueParsedData.slice(i, i + CHUNK_SIZE);
            try {
                const response = await splunkFetch(`${KV_STORE_URL}/batch_save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(chunk),
                });
                if (!response.ok) {
                    hasErrors = true;
                    console.error(`Failed to save chunk starting at index ${i}`);
                }
            } catch (err) {
                hasErrors = true;
                console.error(`Network error on chunk ${i}:`, err);
            }
        }

        if (hasErrors)
            setError(
                'Some batches were not saved successfully. Check the console logs for details.',
            );
        else showSuccess(`Successfully processed bulk upload of ${uniqueParsedData.length} IPs.`);

        await fetchIps();
    };

    const kpiCardStyle: React.CSSProperties = {
        flex: 1,
        minWidth: '250px',
        padding: '20px',
        backgroundColor: 'var(--background-color-secondary, rgba(128, 128, 128, 0.05))',
        borderRadius: '8px',
        border: '1px solid var(--border-color, rgba(128, 128, 128, 0.2))',
        boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        color: 'var(--text-color, inherit)',
    };

    const nowMs = Date.now();

    return (
        <StyledContainer>
            {modalConfig && (
                <Modal
                    onRequestClose={() => setModalConfig(null)}
                    open={modalConfig.isOpen}
                    returnFocus={modalReturnFocusRef}
                    style={{ width: '400px' }}
                >
                    <Modal.Header title={modalConfig.title} />
                    <Modal.Body>{modalConfig.message}</Modal.Body>
                    <Modal.Footer>
                        <Button
                            appearance="secondary"
                            onClick={() => setModalConfig(null)}
                            label="Cancel"
                        />
                        <Button
                            appearance="destructive"
                            onClick={modalConfig.onConfirm}
                            label="Confirm Delete"
                        />
                    </Modal.Footer>
                </Modal>
            )}

            {isLoading && !isInitialLoad && (
                <div
                    style={{
                        position: 'fixed',
                        top: 0,
                        left: 0,
                        width: '100vw',
                        height: '100vh',
                        backgroundColor:
                            'var(--background-color-modal-overlay, rgba(0, 0, 0, 0.4))',
                        zIndex: 9999,
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        alignItems: 'center',
                    }}
                >
                    <WaitSpinner size="large" />
                    <Heading
                        level={3}
                        style={{ marginTop: '20px', color: 'var(--text-color, #fff)' }}
                    >
                        Processing Operation...
                    </Heading>
                    <div
                        style={{
                            color: 'var(--text-color, #fff)',
                            opacity: 0.8,
                            marginTop: '10px',
                            fontSize: '14px',
                        }}
                    >
                        Please wait while the KV Store updates. This may take a few moments for
                        large files.
                    </div>
                </div>
            )}

            {isInitialLoad ? (
                <div
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        height: '60vh',
                    }}
                >
                    <WaitSpinner size="large" />
                    <Heading level={3} style={{ marginTop: '25px', opacity: 0.7 }}>
                        Loading Manual Allowlist...
                    </Heading>
                    <div style={{ opacity: 0.6, marginTop: '10px' }}>
                        Fetching Allowed IPs from KV Store. This might take a moment.
                    </div>
                </div>
            ) : (
                <>
                    <StyledGreeting data-testid="greeting" style={{ marginBottom: '20px' }}>
                        Threat Intelligence IP Allowlist
                    </StyledGreeting>

                    {successMsg && (
                        <div
                            style={{
                                backgroundColor: 'rgba(40, 167, 69, 0.1)',
                                color: '#28a745',
                                border: '1px solid rgba(40, 167, 69, 0.5)',
                                padding: '12px',
                                borderRadius: '4px',
                                marginBottom: '20px',
                                fontSize: '14px',
                            }}
                        >
                            <strong>Success:</strong> {successMsg}
                        </div>
                    )}

                    {error && (
                        <div
                            style={{
                                backgroundColor: 'rgba(211, 9, 9, 0.1)',
                                color: '#ff4c4c',
                                padding: '12px',
                                borderRadius: '4px',
                                marginBottom: '20px',
                                border: '1px solid rgba(211, 9, 9, 0.5)',
                                fontSize: '14px',
                            }}
                        >
                            <strong>Error:</strong> {error}
                        </div>
                    )}

                    <div
                        style={{
                            display: 'flex',
                            gap: '20px',
                            flexWrap: 'wrap',
                            marginBottom: '30px',
                        }}
                    >
                        <div style={kpiCardStyle}>
                            <div
                                style={{
                                    fontSize: '13px',
                                    opacity: 0.7,
                                    textTransform: 'uppercase',
                                    fontWeight: 600,
                                    marginBottom: '8px',
                                }}
                            >
                                Total Active Allows
                            </div>
                            <div style={{ fontSize: '28px', fontWeight: 'bold' }}>
                                {totalActiveIps}
                            </div>
                        </div>
                        <div style={kpiCardStyle}>
                            <div
                                style={{
                                    fontSize: '13px',
                                    opacity: 0.7,
                                    textTransform: 'uppercase',
                                    fontWeight: 600,
                                    marginBottom: '8px',
                                }}
                            >
                                Average Allow Duration
                            </div>
                            <div style={{ fontSize: '28px', fontWeight: 'bold' }}>
                                {averageDurationStr}
                            </div>
                        </div>
                        <div style={kpiCardStyle}>
                            <div
                                style={{
                                    fontSize: '13px',
                                    opacity: 0.7,
                                    textTransform: 'uppercase',
                                    fontWeight: 600,
                                    marginBottom: '8px',
                                }}
                            >
                                Permanent Allows
                            </div>
                            <div style={{ fontSize: '28px', fontWeight: 'bold' }}>
                                {permanentAllowsCount}{' '}
                                <span
                                    style={{
                                        fontSize: '14px',
                                        fontWeight: 'normal',
                                        opacity: 0.7,
                                    }}
                                >
                                    IPs never expire
                                </span>
                            </div>
                        </div>
                    </div>

                    <div
                        style={{
                            backgroundColor:
                                'var(--background-color-secondary, rgba(128, 128, 128, 0.05))',
                            padding: '20px',
                            borderRadius: '8px',
                            border: '1px solid var(--border-color, rgba(128, 128, 128, 0.2))',
                            marginBottom: '30px',
                        }}
                    >
                        <Heading level={4} style={{ marginTop: 0, marginBottom: '15px' }}>
                            Add to Allowlist
                        </Heading>
                        <form
                            onSubmit={handleAddIp}
                            style={{
                                display: 'flex',
                                gap: '15px',
                                alignItems: 'center',
                                flexWrap: 'wrap',
                            }}
                        >
                            <Text
                                value={newIp}
                                onChange={(e: any, { value }: any) => setNewIp(value)}
                                placeholder="IPs (comma separated, max 20)"
                                error={!isFormatValid || isDuplicate || isTooMany}
                                style={{ width: '220px' }}
                            />
                            <Text
                                value={newReason}
                                onChange={(e: any, { value }: any) => setNewReason(value)}
                                placeholder="Reason (Optional)"
                                style={{ width: '200px' }}
                            />

                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    borderLeft:
                                        '1px solid var(--border-color, rgba(128,128,128,0.3))',
                                    paddingLeft: '15px',
                                }}
                            >
                                <span style={{ fontSize: '14px', fontWeight: 500, opacity: 0.9 }}>
                                    Duration:
                                </span>
                                <Text
                                    value={newDurationValue}
                                    onChange={(e: any, { value }: any) =>
                                        setNewDurationValue(value)
                                    }
                                    disabled={newDurationUnit === 'never' || isLoading}
                                    error={!isDurationValid}
                                    style={{ width: '50px' }}
                                />
                                <Select
                                    value={newDurationUnit}
                                    onChange={(e: any, data: any) =>
                                        setNewDurationUnit(data.value as DurationUnit)
                                    }
                                    style={{ width: '100px' }}
                                    disabled={isLoading}
                                >
                                    <Select.Option label="Minutes" value="m" />
                                    <Select.Option label="Hours" value="h" />
                                    <Select.Option label="Days" value="d" />
                                    <Select.Option label="Never" value="never" />
                                </Select>
                            </div>

                            <Button
                                type="submit"
                                label="Add IP(s)"
                                appearance={isAddBtnDisabled ? 'secondary' : 'primary'}
                                disabled={isAddBtnDisabled}
                                style={{ marginLeft: 'auto' }}
                            />

                            <div
                                style={{
                                    borderLeft:
                                        '1px solid var(--border-color, rgba(128,128,128,0.3))',
                                    height: '30px',
                                }}
                            ></div>

                            <input
                                type="file"
                                accept=".txt,.csv"
                                ref={fileInputRef}
                                style={{ display: 'none' }}
                                onChange={handleFileChange}
                            />
                            <Button
                                label="Bulk Upload"
                                appearance="secondary"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isBulkBtnDisabled}
                            />
                        </form>

                        {!isFormatValid && !isTooMany && (
                            <div style={{ color: '#ff4c4c', fontSize: '12px', marginTop: '8px' }}>
                                Invalid format. Ensure IPs are valid (e.g., 192.168.1.1 or
                                10.0.0.0/24).
                            </div>
                        )}
                        {!isDurationValid && (
                            <div style={{ color: '#ff4c4c', fontSize: '12px', marginTop: '8px' }}>
                                Please enter a valid number greater than 0 for the duration.
                            </div>
                        )}
                        {isTooMany && (
                            <div
                                style={{
                                    color: '#ff4c4c',
                                    fontSize: '12px',
                                    marginTop: '8px',
                                    fontWeight: 'bold',
                                }}
                            >
                                Max 20 IPs allowed manually. For larger sets, please use Bulk
                                Upload.
                            </div>
                        )}
                        {isFormatValid && isDuplicate && (
                            <div
                                style={{
                                    color: '#ff4c4c',
                                    fontSize: '12px',
                                    fontWeight: 'bold',
                                    marginTop: '8px',
                                }}
                            >
                                One or more entered IPs are already in the allowlist.
                            </div>
                        )}
                    </div>

                    {fileLists.length > 0 && (
                        <div style={{ marginBottom: '30px' }}>
                            <Heading level={4} style={{ marginTop: 0, marginBottom: '15px' }}>
                                Uploaded Lists Management
                            </Heading>
                            <div
                                style={{
                                    border: '1px solid var(--border-color, rgba(128, 128, 128, 0.2))',
                                    borderRadius: '8px',
                                    overflow: 'hidden',
                                }}
                            >
                                <Table stripeRows>
                                    <Table.Head>
                                        <Table.HeadCell>File Name</Table.HeadCell>
                                        <Table.HeadCell>Subnets Count</Table.HeadCell>
                                        <Table.HeadCell>Uploaded By</Table.HeadCell>
                                        <Table.HeadCell>Date</Table.HeadCell>
                                        <Table.HeadCell style={{ width: '180px' }}>
                                            Actions
                                        </Table.HeadCell>
                                    </Table.Head>
                                    <Table.Body>
                                        {fileLists.map((list) => (
                                            <Table.Row key={list.source}>
                                                <Table.Cell style={{ fontWeight: 'bold' }}>
                                                    {list.source}
                                                </Table.Cell>
                                                <Table.Cell>{list.count}</Table.Cell>
                                                <Table.Cell>{list.user}</Table.Cell>
                                                <Table.Cell>
                                                    {formatTimestamp(list.timestamp)}
                                                </Table.Cell>
                                                <Table.Cell>
                                                    <Button
                                                        label="Remove Entire List"
                                                        appearance="destructive"
                                                        onClick={() =>
                                                            confirmRemoveList(
                                                                list.keys,
                                                                list.source,
                                                            )
                                                        }
                                                        disabled={isLoading}
                                                    />
                                                </Table.Cell>
                                            </Table.Row>
                                        ))}
                                    </Table.Body>
                                </Table>
                            </div>
                        </div>
                    )}

                    <Heading level={4} style={{ marginTop: 0, marginBottom: '15px' }}>
                        All Allowed IPs
                    </Heading>
                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            marginBottom: '15px',
                        }}
                    >
                        <Text
                            value={searchQuery}
                            onChange={(e: any, { value }: any) => setSearchQuery(value)}
                            placeholder="Search by IP, User, File, or Reason..."
                            canClear
                            style={{ width: '350px' }}
                        />

                        <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                            {selectedKeys.length > 0 && (
                                <Button
                                    label={`Delete Selected (${selectedKeys.length})`}
                                    appearance="destructive"
                                    onClick={confirmBulkRemove}
                                    disabled={isLoading}
                                />
                            )}

                            <div
                                style={{
                                    borderLeft:
                                        '1px solid var(--border-color, rgba(128,128,128,0.3))',
                                    height: '20px',
                                }}
                            ></div>

                            <span style={{ fontSize: '14px', opacity: 0.9, fontWeight: 500 }}>
                                Rows per page:
                            </span>
                            <Select
                                value={pageSize}
                                onChange={(e: any, data: any) => setPageSize(Number(data.value))}
                                style={{ width: '80px' }}
                            >
                                <Select.Option label="5" value={5} />
                                <Select.Option label="10" value={10} />
                                <Select.Option label="25" value={25} />
                                <Select.Option label="50" value={50} />
                            </Select>
                        </div>
                    </div>

                    <div
                        style={{
                            border: '1px solid var(--border-color, rgba(128, 128, 128, 0.2))',
                            borderRadius: '8px',
                            overflow: 'hidden',
                        }}
                    >
                        <Table stripeRows>
                            <Table.Head>
                                <Table.HeadCell style={{ width: '40px', textAlign: 'center' }}>
                                    <input
                                        type="checkbox"
                                        checked={allPageSelected}
                                        onChange={handleToggleAll}
                                        disabled={paginatedIps.length === 0}
                                        style={{ cursor: 'pointer', width: '16px', height: '16px' }}
                                        title="Select all on this page"
                                    />
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="ip"
                                    sortDir={sortState.key === 'ip' ? sortState.dir : 'none'}
                                >
                                    IP Address (CIDR)
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="source"
                                    sortDir={sortState.key === 'source' ? sortState.dir : 'none'}
                                >
                                    Source
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="user"
                                    sortDir={sortState.key === 'user' ? sortState.dir : 'none'}
                                >
                                    Submitted By
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="reason"
                                    sortDir={sortState.key === 'reason' ? sortState.dir : 'none'}
                                >
                                    Reason
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="timestamp"
                                    sortDir={sortState.key === 'timestamp' ? sortState.dir : 'none'}
                                >
                                    Allowed On
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="expirydate"
                                    sortDir={
                                        sortState.key === 'expirydate' ? sortState.dir : 'none'
                                    }
                                >
                                    Expiry Date
                                </Table.HeadCell>
                            </Table.Head>
                            <Table.Body>
                                {paginatedIps.length === 0 ? (
                                    <Table.Row>
                                        <Table.Cell
                                            colSpan={7}
                                            style={{
                                                textAlign: 'center',
                                                padding: '30px',
                                                opacity: 0.7,
                                            }}
                                        >
                                            {isLoading
                                                ? 'Loading data...'
                                                : debouncedSearchQuery
                                                  ? 'No IPs match your search.'
                                                  : 'No IPs found in the allowlist.'}
                                        </Table.Cell>
                                    </Table.Row>
                                ) : (
                                    paginatedIps.map((row) => {
                                        const isExpired =
                                            row.expirydate &&
                                            new Date(row.expirydate).getTime() <= nowMs;
                                        const isExpiringSoon =
                                            row.expirydate &&
                                            new Date(row.expirydate).getTime() - nowMs <=
                                                86400000 &&
                                            !isExpired;
                                        return (
                                            <Table.Row
                                                key={row._key}
                                                style={{ opacity: isExpired ? 0.6 : 1 }}
                                            >
                                                <Table.Cell style={{ textAlign: 'center' }}>
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedKeysSet.has(row._key)}
                                                        onChange={() => handleToggleRow(row._key)}
                                                        style={{
                                                            cursor: 'pointer',
                                                            width: '16px',
                                                            height: '16px',
                                                        }}
                                                        aria-label={`Select ${row.ip}`}
                                                    />
                                                </Table.Cell>
                                                <Table.Cell
                                                    style={{
                                                        fontFamily: 'monospace',
                                                        fontSize: '14px',
                                                        textDecoration: isExpired
                                                            ? 'line-through'
                                                            : 'none',
                                                    }}
                                                >
                                                    {row.ip}
                                                </Table.Cell>
                                                <Table.Cell>
                                                    {row.source || 'Manual Entry'}
                                                </Table.Cell>
                                                <Table.Cell>{row.user || 'Unknown'}</Table.Cell>
                                                <Table.Cell>{row.reason || '-'}</Table.Cell>
                                                <Table.Cell>
                                                    {formatTimestamp(row.timestamp)}
                                                </Table.Cell>
                                                <Table.Cell
                                                    style={{
                                                        fontWeight: !row.expirydate
                                                            ? 'bold'
                                                            : 'normal',
                                                        color: !row.expirydate
                                                            ? '#28a745'
                                                            : isExpired
                                                              ? '#888'
                                                              : isExpiringSoon
                                                                ? '#ff4c4c'
                                                                : 'inherit',
                                                    }}
                                                >
                                                    {row.expirydate
                                                        ? isExpired
                                                            ? `Expired (${formatTimestamp(row.expirydate)})`
                                                            : formatTimestamp(row.expirydate)
                                                        : 'Never'}
                                                </Table.Cell>
                                            </Table.Row>
                                        );
                                    })
                                )}
                            </Table.Body>
                        </Table>
                    </div>

                    {totalPages > 1 && (
                        <div
                            style={{ display: 'flex', justifyContent: 'center', marginTop: '20px' }}
                        >
                            <Paginator
                                current={currentPage}
                                totalPages={totalPages}
                                onChange={(e: any, { page }: any) => setCurrentPage(page)}
                            />
                        </div>
                    )}
                </>
            )}
        </StyledContainer>
    );
};

export default ManualAllow;
