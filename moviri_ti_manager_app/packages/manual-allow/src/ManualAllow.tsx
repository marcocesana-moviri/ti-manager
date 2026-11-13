import React, { useState, useEffect, useRef, useMemo } from 'react';
import Button from '@splunk/react-ui/Button';
import Text from '@splunk/react-ui/Text';
import Table from '@splunk/react-ui/Table';
import Select from '@splunk/react-ui/Select';
import Paginator from '@splunk/react-ui/Paginator';
import Heading from '@splunk/react-ui/Heading';
import WaitSpinner from '@splunk/react-ui/WaitSpinner';

import { defaultFetchInit } from '@splunk/splunk-utils/fetch';

import { StyledContainer, StyledGreeting } from './ManualAllowStyles';

const APP_NAME = 'moviri_ti_manager_app';
const COLLECTION_NAME = 'manual_allowlist';

const locale = window.location.pathname.split('/')[1] || 'en-US';
const KV_STORE_URL = `/${locale}/splunkd/__raw/servicesNS/nobody/${APP_NAME}/storage/collections/data/${COLLECTION_NAME}`;

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
    return input
        .split(/[\s,;]+/)
        .map((ip) => ip.trim())
        .filter((ip) => ip.length > 0)
        .map((ip) => (ip.includes('/') ? ip : `${ip}/32`));
};

const formatTimestamp = (isoString?: string) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return isNaN(date.getTime()) ? '-' : date.toLocaleString();
};

const calculateExpiryDate = (val: string, unit: string): string => {
    if (unit === 'never') return '';
    const now = new Date();
    const num = parseInt(val, 10) || 0;

    if (num <= 0) return '';

    if (unit === 'm') now.setMinutes(now.getMinutes() + num);
    if (unit === 'h') now.setHours(now.getHours() + num);
    if (unit === 'd') now.setDate(now.getDate() + num);

    return now.toISOString();
};

const ManualAllow: React.FC = () => {
    const [ips, setIps] = useState<IPRow[]>([]);

    const [newIp, setNewIp] = useState<string>('');
    const [newUser, setNewUser] = useState<string>('');
    const [newReason, setNewReason] = useState<string>('');

    const [newDurationValue, setNewDurationValue] = useState<string>('24');
    const [newDurationUnit, setNewDurationUnit] = useState<string>('h');

    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [isInitialLoad, setIsInitialLoad] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);

    const [searchQuery, setSearchQuery] = useState<string>('');
    const [currentPage, setCurrentPage] = useState<number>(1);
    const [pageSize, setPageSize] = useState<number>(10);
    const [sortKey, setSortKey] = useState<keyof IPRow | 'none'>('none');
    const [sortDir, setSortDir] = useState<'asc' | 'desc' | 'none'>('none');

    const [selectedKeys, setSelectedKeys] = useState<string[]>([]);

    const fileInputRef = useRef<HTMLInputElement>(null);

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
    }, []);

    useEffect(() => {
        setCurrentPage(1);
        setSelectedKeys([]);
    }, [searchQuery, ips.length, pageSize, sortKey, sortDir]);

    const fetchIps = async () => {
        setIsLoading(true);
        setError(null);

        try {
            let allFetchedIps: IPRow[] = [];
            let currentSkip = 0;
            const CHUNK_LIMIT = 50000;
            let keepFetching = true;

            while (keepFetching) {
                const response = await splunkFetch(
                    `${KV_STORE_URL}?limit=${CHUNK_LIMIT}&skip=${currentSkip}`,
                );

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(
                        `Failed to fetch chunk at skip ${currentSkip} (${response.status}): ${errorText}`,
                    );
                }

                const chunk: IPRow[] = await response.json();
                allFetchedIps = [...allFetchedIps, ...chunk];

                if (chunk.length < CHUNK_LIMIT) {
                    keepFetching = false;
                } else {
                    currentSkip += CHUNK_LIMIT;
                }
            }

            setIps(allFetchedIps);
        } catch (err: any) {
            setError(`Network error while fetching data: ${err.message || String(err)}`);
        } finally {
            setIsLoading(false);
            setIsInitialLoad(false);
        }
    };

    // --- KPI Computations ---
    const totalActiveIps = ips.length;

    const permanentAllowsCount = ips.filter((row) => !row.expirydate).length;

    const averageDurationStr = useMemo(() => {
        let totalMs = 0;
        let count = 0;
        ips.forEach((row) => {
            if (row.expirydate && row.timestamp) {
                const start = new Date(row.timestamp).getTime();
                const end = new Date(row.expirydate).getTime();
                if (!isNaN(start) && !isNaN(end) && end > start) {
                    totalMs += end - start;
                    count++;
                }
            }
        });
        if (count === 0) return 'N/A';
        const avgHours = totalMs / count / (1000 * 60 * 60);
        if (avgHours < 1) return `${(avgHours * 60).toFixed(0)} Mins`;
        if (avgHours > 24) return `${(avgHours / 24).toFixed(1)} Days`;
        return `${avgHours.toFixed(1)} Hours`;
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

    const filteredIps = ips.filter((row) => {
        const query = searchQuery.toLowerCase();
        return (
            row.ip.toLowerCase().includes(query) ||
            (row.user && row.user.toLowerCase().includes(query)) ||
            (row.reason && row.reason.toLowerCase().includes(query)) ||
            (row.source && row.source.toLowerCase().includes(query))
        );
    });

    const sortedIps = [...filteredIps].sort((a, b) => {
        if (sortDir === 'none' || sortKey === 'none') return 0;
        const valA = (a[sortKey] || '').toLowerCase();
        const valB = (b[sortKey] || '').toLowerCase();

        if (valA < valB) return sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    const totalPages = Math.max(1, Math.ceil(sortedIps.length / pageSize));
    const paginatedIps = sortedIps.slice((currentPage - 1) * pageSize, currentPage * pageSize);

    const allPageSelected =
        paginatedIps.length > 0 && paginatedIps.every((row) => selectedKeys.includes(row._key));

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
        if (sortKey === newSortKey) {
            setSortDir((prev) => (prev === 'asc' ? 'desc' : prev === 'desc' ? 'none' : 'asc'));
            if (sortDir === 'desc') setSortKey('none');
        } else {
            setSortKey(newSortKey as keyof IPRow);
            setSortDir('asc');
        }
    };

    const ipsToAdd = useMemo(() => parseAndNormalizeIps(newIp), [newIp]);
    const isInputEmpty = ipsToAdd.length === 0;
    const isTooMany = ipsToAdd.length > 20;
    const isFormatValid = isInputEmpty || ipsToAdd.every(isValidCIDR);
    const isDuplicate = ipsToAdd.some((ip) => ips.some((row) => row.ip === ip));
    const isDurationValid =
        newDurationUnit === 'never' ||
        (!isNaN(Number(newDurationValue)) && Number(newDurationValue) > 0);

    const handleAddIp = async () => {
        if (!isFormatValid || isDuplicate || isTooMany || isInputEmpty || !isDurationValid) return;

        setError(null);
        setIsLoading(true);
        const nowIso = new Date().toISOString();
        const expiryIso = calculateExpiryDate(newDurationValue, newDurationUnit);

        const payload = ipsToAdd.map((ip) => ({
            _key: ip,
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
            await fetchIps();
        } catch (err: any) {
            setError(`Network error while saving: ${err.message || String(err)}`);
            setIsLoading(false);
        }
    };

    const performBatchDelete = async (keysToRemove: string[]) => {
        let hasErrors = false;
        const CHUNK_SIZE = 100;

        for (let i = 0; i < keysToRemove.length; i += CHUNK_SIZE) {
            const keysChunk = keysToRemove.slice(i, i + CHUNK_SIZE);
            const queryJson = JSON.stringify({ _key: { $in: keysChunk } });

            try {
                const response = await splunkFetch(
                    `${KV_STORE_URL}?query=${encodeURIComponent(queryJson)}`,
                    { method: 'DELETE' },
                );
                if (!response.ok) {
                    hasErrors = true;
                    console.error(`Failed to batch delete chunk starting at index ${i}`);
                }
            } catch (err) {
                hasErrors = true;
                console.error(
                    `Network error on batch delete for chunk starting at index ${i}:`,
                    err,
                );
            }
        }
        return hasErrors;
    };

    const handleBulkRemove = async () => {
        if (selectedKeys.length === 0) return;
        setError(null);
        setIsLoading(true);

        const hasErrors = await performBatchDelete(selectedKeys);
        if (hasErrors)
            setError('Some selected items could not be deleted successfully. Check console logs.');

        setSelectedKeys([]);
        await fetchIps();
    };

    const handleRemoveList = async (keysToRemove: string[]) => {
        if (keysToRemove.length === 0) return;
        setError(null);
        setIsLoading(true);

        const hasErrors = await performBatchDelete(keysToRemove);
        if (hasErrors)
            setError(
                'Some items from the list could not be deleted successfully. Check console logs.',
            );

        setSelectedKeys((prev) => prev.filter((k) => !keysToRemove.includes(k)));
        await fetchIps();
    };

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const fileName = file.name;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const text = e.target?.result as string;
            if (text) {
                await processBulkIps(text, fileName);
            }
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
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

        const parsedData = lines.map((line) => {
            const parts = line.split(',');
            const rawIp = parts[0]?.trim() || '';
            const ip = rawIp.includes('/') ? rawIp : `${rawIp}/32`;

            return {
                _key: ip,
                ip: ip,
                user: parts[1]?.trim() || newUser.trim() || 'Unknown',
                reason: parts[2]?.trim() || newReason.trim() || 'Bulk upload',
                timestamp: now,
                expirydate: expiryIso,
                source: fileName,
            };
        });

        const invalidEntries = parsedData.filter((entry) => !isValidCIDR(entry.ip));
        if (invalidEntries.length > 0) {
            setError(
                `Upload blocked: Found ${invalidEntries.length} invalid CIDR formats (e.g., "${invalidEntries[0].ip}"). Ensure file format is IP,User,Reason.`,
            );
            setIsLoading(false);
            return;
        }

        const existingIps = new Set(ips.map((row) => row.ip));
        const uniqueParsedData = [];
        const seenInFile = new Set();

        for (const entry of parsedData) {
            if (!existingIps.has(entry.ip) && !seenInFile.has(entry.ip)) {
                uniqueParsedData.push(entry);
                seenInFile.add(entry.ip);
            }
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
            } catch (err: any) {
                hasErrors = true;
                console.error(`Network error on chunk starting at index ${i}:`, err);
            }
        }

        if (hasErrors) {
            setError(
                'Some batches were not saved successfully. Check the console logs for details.',
            );
        }

        await fetchIps();
    };

    const kpiCardStyle = {
        flex: 1,
        minWidth: '250px',
        padding: '20px',
        backgroundColor: '#ffffff',
        borderRadius: '8px',
        border: '1px solid #e1e6eb',
        boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column' as const,
        justifyContent: 'center',
    };

    const kpiTitleStyle = {
        fontSize: '13px',
        color: '#656d76',
        textTransform: 'uppercase' as const,
        fontWeight: 600,
        marginBottom: '8px',
    };

    const kpiValueStyle = {
        fontSize: '28px',
        fontWeight: 'bold',
        color: '#1e252b',
    };

    return (
        <StyledContainer>
            {isLoading && !isInitialLoad && (
                <div
                    style={{
                        position: 'fixed',
                        top: 0,
                        left: 0,
                        width: '100vw',
                        height: '100vh',
                        backgroundColor: 'rgba(255, 255, 255, 0.75)',
                        zIndex: 9999,
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        alignItems: 'center',
                    }}
                >
                    <WaitSpinner size="large" />
                    <Heading level={3} style={{ marginTop: '20px', color: '#1e252b' }}>
                        Processing Operation...
                    </Heading>
                    <div style={{ color: '#656d76', marginTop: '10px', fontSize: '14px' }}>
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
                    <Heading level={3} style={{ marginTop: '25px', color: '#656d76' }}>
                        Loading Manual Allowlist...
                    </Heading>
                    <div style={{ color: '#8c959f', marginTop: '10px' }}>
                        Fetching Allowed IPs from KV Store. This might take a moment.
                    </div>
                </div>
            ) : (
                <>
                    <StyledGreeting data-testid="greeting" style={{ marginBottom: '20px' }}>
                        Threat Intelligence IP Allowlist
                    </StyledGreeting>

                    {error && (
                        <div
                            style={{
                                backgroundColor: '#fcdcdc',
                                color: '#d30909',
                                padding: '12px',
                                borderRadius: '4px',
                                marginBottom: '20px',
                                border: '1px solid #d30909',
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
                            <div style={kpiTitleStyle}>Total Active Allows</div>
                            <div style={kpiValueStyle}>{totalActiveIps}</div>
                        </div>
                        <div style={kpiCardStyle}>
                            <div style={kpiTitleStyle}>Average Allow Duration</div>
                            <div style={kpiValueStyle}>{averageDurationStr}</div>
                        </div>
                        <div style={kpiCardStyle}>
                            <div style={kpiTitleStyle}>Permanent Allows</div>
                            <div style={kpiValueStyle}>
                                {permanentAllowsCount}{' '}
                                <span
                                    style={{
                                        fontSize: '14px',
                                        fontWeight: 'normal',
                                        color: '#656d76',
                                    }}
                                >
                                    IPs never expire
                                </span>
                            </div>
                        </div>
                    </div>

                    <div
                        style={{
                            backgroundColor: '#f8f9fa',
                            padding: '20px',
                            borderRadius: '8px',
                            border: '1px solid #e1e6eb',
                            marginBottom: '30px',
                        }}
                    >
                        <Heading level={4} style={{ marginTop: 0, marginBottom: '15px' }}>
                            Add to Allowlist
                        </Heading>
                        <div
                            style={{
                                display: 'flex',
                                gap: '15px',
                                alignItems: 'center',
                                flexWrap: 'wrap',
                            }}
                        >
                            <Text
                                value={newIp}
                                onChange={(e, { value }: { value: string }) => setNewIp(value)}
                                placeholder="IPs (comma separated, max 20)"
                                error={!isFormatValid || isDuplicate || isTooMany}
                                style={{ width: '220px' }}
                            />
                            <Text
                                value={newReason}
                                onChange={(e, { value }: { value: string }) => setNewReason(value)}
                                placeholder="Reason (Optional)"
                                style={{ width: '200px' }}
                            />

                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    borderLeft: '1px solid #ccc',
                                    paddingLeft: '15px',
                                }}
                            >
                                <span
                                    style={{ fontSize: '14px', fontWeight: 500, color: '#3C444D' }}
                                >
                                    Duration:
                                </span>
                                <Text
                                    value={newDurationValue}
                                    onChange={(e, { value }: { value: string }) =>
                                        setNewDurationValue(value)
                                    }
                                    disabled={newDurationUnit === 'never' || isLoading}
                                    error={!isDurationValid}
                                    style={{ width: '50px' }}
                                />
                                <Select
                                    value={newDurationUnit}
                                    onChange={(e: any, data: any) => setNewDurationUnit(data.value)}
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
                                label="Add IP(s)"
                                appearance="primary"
                                onClick={handleAddIp}
                                disabled={
                                    isInputEmpty ||
                                    !isFormatValid ||
                                    isDuplicate ||
                                    isTooMany ||
                                    !isDurationValid ||
                                    isLoading
                                }
                                style={{ marginLeft: 'auto' }}
                            />

                            <div
                                style={{
                                    borderLeft: '1px solid #ccc',
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
                                disabled={isLoading || !isDurationValid}
                            />
                        </div>

                        {!isFormatValid && !isTooMany && (
                            <div style={{ color: '#d30909', fontSize: '12px', marginTop: '8px' }}>
                                Invalid format. Ensure IPs are valid (e.g., 192.168.1.1 or
                                10.0.0.0/24).
                            </div>
                        )}
                        {!isDurationValid && (
                            <div style={{ color: '#d30909', fontSize: '12px', marginTop: '8px' }}>
                                Please enter a valid number greater than 0 for the duration.
                            </div>
                        )}
                        {isTooMany && (
                            <div
                                style={{
                                    color: '#d30909',
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
                                    color: '#d30909',
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
                                    border: '1px solid #e1e6eb',
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
                                                        onClick={() => handleRemoveList(list.keys)}
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
                            onChange={(e, { value }: { value: string }) => setSearchQuery(value)}
                            placeholder="Search by IP, User, Source, or Reason..."
                            canClear
                            style={{ width: '350px' }}
                        />

                        <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                            {selectedKeys.length > 0 && (
                                <Button
                                    label={`Delete Selected (${selectedKeys.length})`}
                                    appearance="destructive"
                                    onClick={handleBulkRemove}
                                    disabled={isLoading}
                                />
                            )}

                            <div style={{ borderLeft: '1px solid #ccc', height: '20px' }}></div>

                            <span style={{ fontSize: '14px', color: '#3C444D', fontWeight: 500 }}>
                                Rows per page:
                            </span>
                            <Select
                                value={pageSize}
                                onChange={(e: any, data: any) => setPageSize(data.value)}
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
                            border: '1px solid #e1e6eb',
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
                                    sortDir={sortKey === 'ip' ? sortDir : 'none'}
                                >
                                    IP Address (CIDR)
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="source"
                                    sortDir={sortKey === 'source' ? sortDir : 'none'}
                                >
                                    Source
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="user"
                                    sortDir={sortKey === 'user' ? sortDir : 'none'}
                                >
                                    Submitted By
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="reason"
                                    sortDir={sortKey === 'reason' ? sortDir : 'none'}
                                >
                                    Reason
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="timestamp"
                                    sortDir={sortKey === 'timestamp' ? sortDir : 'none'}
                                >
                                    Allowed On
                                </Table.HeadCell>
                                <Table.HeadCell
                                    onSort={handleSort}
                                    sortKey="expirydate"
                                    sortDir={sortKey === 'expirydate' ? sortDir : 'none'}
                                >
                                    Expiry Date
                                </Table.HeadCell>
                            </Table.Head>
                            <Table.Body>
                                {paginatedIps.length === 0 ? (
                                    <Table.Row>
                                        <Table.Cell
                                            colSpan={8}
                                            style={{
                                                textAlign: 'center',
                                                padding: '30px',
                                                color: '#656d76',
                                            }}
                                        >
                                            {isLoading
                                                ? 'Loading data...'
                                                : searchQuery
                                                  ? 'No IPs match your search.'
                                                  : 'No IPs found in the allowlist.'}
                                        </Table.Cell>
                                    </Table.Row>
                                ) : (
                                    paginatedIps.map((row) => (
                                        <Table.Row key={row._key}>
                                            <Table.Cell style={{ textAlign: 'center' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={selectedKeys.includes(row._key)}
                                                    onChange={() => handleToggleRow(row._key)}
                                                    style={{
                                                        cursor: 'pointer',
                                                        width: '16px',
                                                        height: '16px',
                                                    }}
                                                />
                                            </Table.Cell>
                                            <Table.Cell
                                                style={{
                                                    fontFamily: 'monospace',
                                                    fontSize: '14px',
                                                }}
                                            >
                                                {row.ip}
                                            </Table.Cell>
                                            <Table.Cell>{row.source || 'Manual Entry'}</Table.Cell>
                                            <Table.Cell>{row.user || 'Unknown'}</Table.Cell>
                                            <Table.Cell>{row.reason || '-'}</Table.Cell>
                                            <Table.Cell>
                                                {formatTimestamp(row.timestamp)}
                                            </Table.Cell>
                                            <Table.Cell
                                                style={{
                                                    fontWeight: 'bold',
                                                    color: row.expirydate ? '#656d76' : '#28a745',
                                                }}
                                            >
                                                {row.expirydate
                                                    ? formatTimestamp(row.expirydate)
                                                    : 'Never'}
                                            </Table.Cell>
                                        </Table.Row>
                                    ))
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
                                onChange={(e, { page }: { page: number }) => setCurrentPage(page)}
                            />
                        </div>
                    )}
                </>
            )}
        </StyledContainer>
    );
};

export default ManualAllow;
