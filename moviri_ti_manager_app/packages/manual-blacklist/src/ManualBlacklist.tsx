import React, { useState, useEffect, useRef, useMemo } from 'react';
import Button from '@splunk/react-ui/Button';
import Text from '@splunk/react-ui/Text';
import Table from '@splunk/react-ui/Table';
import Select from '@splunk/react-ui/Select';
import Paginator from '@splunk/react-ui/Paginator';
import Heading from '@splunk/react-ui/Heading';
import WaitSpinner from '@splunk/react-ui/WaitSpinner';

import { defaultFetchInit } from '@splunk/splunk-utils/fetch';

import { StyledContainer, StyledGreeting } from './ManualBlacklistStyles';

const APP_NAME = 'moviri_ti_manager_app';
const COLLECTION_NAME = 'manual_blacklist';

const locale = window.location.pathname.split('/')[1] || 'en-US';
const KV_STORE_URL = `/${locale}/splunkd/__raw/servicesNS/nobody/${APP_NAME}/storage/collections/data/${COLLECTION_NAME}`;

interface IPRow {
    _key: string;
    ip: string;
    user: string;
    reason: string;
    timestamp: string;
    filename?: string;
}

interface FileListGroup {
    filename: string;
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

const formatTimestamp = (isoString?: string) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return isNaN(date.getTime()) ? '-' : date.toLocaleString();
};

const ManualBlacklist: React.FC = () => {
    const [ips, setIps] = useState<IPRow[]>([]);

    const [newIp, setNewIp] = useState<string>('');
    const [newUser, setNewUser] = useState<string>('');
    const [newReason, setNewReason] = useState<string>('');

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

    // --- KPI & Grouping Computations ---
    const totalIps = ips.length;
    const uniqueUsersCount = new Set(ips.map((row) => row.user || 'Unknown')).size;

    const userFrequencies = ips.reduce(
        (acc, row) => {
            const u = row.user || 'Unknown';
            acc[u] = (acc[u] || 0) + 1;
            return acc;
        },
        {} as Record<string, number>,
    );

    let topUser = '-';
    let topUserCount = 0;
    for (const [user, count] of Object.entries(userFrequencies)) {
        if (count > topUserCount) {
            topUserCount = count;
            topUser = user;
        }
    }

    // Gruppo logico per i file caricati
    const fileLists = useMemo(() => {
        const groups: Record<string, FileListGroup> = {};
        ips.forEach((row) => {
            if (row.filename) {
                if (!groups[row.filename]) {
                    groups[row.filename] = {
                        filename: row.filename,
                        count: 0,
                        user: row.user,
                        timestamp: row.timestamp,
                        keys: [],
                    };
                }
                groups[row.filename].count += 1;
                groups[row.filename].keys.push(row._key);
            }
        });
        return Object.values(groups).sort(
            (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        );
    }, [ips]);

    // --- Filtering & Sorting ---
    const filteredIps = ips.filter((row) => {
        const query = searchQuery.toLowerCase();
        return (
            row.ip.toLowerCase().includes(query) ||
            (row.user && row.user.toLowerCase().includes(query)) ||
            (row.reason && row.reason.toLowerCase().includes(query)) ||
            (row.filename && row.filename.toLowerCase().includes(query))
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

    // --- Action Handlers ---
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

    const isInputEmpty = newIp.trim() === '';
    const isFormatValid = isInputEmpty || isValidCIDR(newIp.trim());
    const isDuplicate = ips.some((row) => row.ip === newIp.trim());

    const handleAddIp = async () => {
        const trimmedIp = newIp.trim();
        if (!isValidCIDR(trimmedIp) || isDuplicate) return;

        setError(null);
        setIsLoading(true);
        try {
            const response = await splunkFetch(KV_STORE_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ip: trimmedIp,
                    user: newUser.trim() || 'Unknown',
                    reason: newReason.trim() || 'No reason provided',
                    timestamp: new Date().toISOString(),
                }),
            });

            if (response.ok) {
                setNewIp('');
                setNewReason('');
                await fetchIps();
            } else {
                const errorText = await response.text();
                setError(`Failed to add IP (${response.status}): ${errorText}`);
                setIsLoading(false);
            }
        } catch (err: any) {
            setError(`Network error while saving: ${err.message || String(err)}`);
            setIsLoading(false);
        }
    };

    // Generic Batch Delete Function (usato sia per le selezioni manuali che per le liste)
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
        if (hasErrors) {
            setError(
                'Some selected items could not be deleted successfully. Check console logs for details.',
            );
        }

        setSelectedKeys([]);
        await fetchIps();
    };

    // Handler per rimuovere un'intera lista tramite bottone dedicato
    const handleRemoveList = async (keysToRemove: string[]) => {
        if (keysToRemove.length === 0) return;
        setError(null);
        setIsLoading(true);

        const hasErrors = await performBatchDelete(keysToRemove);
        if (hasErrors) {
            setError(
                'Some items from the list could not be deleted successfully. Check console logs.',
            );
        }

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

        const parsedData = lines.map((line) => {
            const parts = line.split(',');
            return {
                ip: parts[0]?.trim() || '',
                user: parts[1]?.trim() || newUser.trim() || 'Unknown',
                reason: parts[2]?.trim() || newReason.trim() || 'Bulk upload',
                timestamp: now,
                filename: fileName, // Aggiunto il nome del file al payload
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
                'All the IPs in this file are already present in the blacklist. No new IPs were added.',
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
        minWidth: '200px',
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
            {/* OVERLAY DI CARICAMENTO PER LE OPERAZIONI IN CORSO */}
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
                        Loading Manual Blacklist...
                    </Heading>
                    <div style={{ color: '#8c959f', marginTop: '10px' }}>
                        Fetching Blacklist IPs from KV Store. This might take a moment.
                    </div>
                </div>
            ) : (
                <>
                    <StyledGreeting data-testid="greeting" style={{ marginBottom: '20px' }}>
                        Threat Intelligence IP Blacklist
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
                            <div style={kpiTitleStyle}>Total Blacklisted IPs</div>
                            <div style={kpiValueStyle}>{totalIps}</div>
                        </div>
                        <div style={kpiCardStyle}>
                            <div style={kpiTitleStyle}>Unique Users</div>
                            <div style={kpiValueStyle}>{uniqueUsersCount}</div>
                        </div>
                        <div style={kpiCardStyle}>
                            <div style={kpiTitleStyle}>Top Submitter</div>
                            <div style={{ ...kpiValueStyle, fontSize: '22px' }}>
                                {topUser}{' '}
                                <span
                                    style={{
                                        fontSize: '14px',
                                        fontWeight: 'normal',
                                        color: '#656d76',
                                    }}
                                >
                                    ({topUserCount} IPs)
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
                            Add to Blacklist
                        </Heading>
                        <div
                            style={{
                                display: 'flex',
                                gap: '10px',
                                alignItems: 'center',
                                flexWrap: 'wrap',
                            }}
                        >
                            <Text
                                value={newIp}
                                onChange={(e, { value }: { value: string }) => setNewIp(value)}
                                placeholder="IP (e.g. 192.168.1.0/24)"
                                error={!isFormatValid || isDuplicate}
                                style={{ width: '220px' }}
                            />
                            <Text
                                value={newUser}
                                onChange={(e, { value }: { value: string }) => setNewUser(value)}
                                disabled
                                style={{ width: '150px' }}
                            />
                            <Text
                                value={newReason}
                                onChange={(e, { value }: { value: string }) => setNewReason(value)}
                                placeholder="Reason (Optional)"
                                style={{ width: '250px' }}
                            />
                            <Button
                                label="Add Single IP"
                                appearance="primary"
                                onClick={handleAddIp}
                                disabled={
                                    isInputEmpty || !isFormatValid || isDuplicate || isLoading
                                }
                            />

                            <div
                                style={{
                                    borderLeft: '1px solid #ccc',
                                    height: '30px',
                                    margin: '0 10px',
                                }}
                            ></div>

                            <input
                                type="file"
                                accept=".txt"
                                ref={fileInputRef}
                                style={{ display: 'none' }}
                                onChange={handleFileChange}
                            />

                            <Button
                                label="Bulk Upload (TXT)"
                                appearance="secondary"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isLoading}
                            />
                        </div>

                        {!isFormatValid && (
                            <div style={{ color: '#d30909', fontSize: '12px', marginTop: '8px' }}>
                                Invalid CIDR format. Ensure you provide an IP and a subnet mask
                                (e.g., 192.168.1.0/24).
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
                                This IP is already in the blacklist.
                            </div>
                        )}
                    </div>

                    {/* SEZIONE: UPLOADED LISTS MANAGEMENT */}
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
                                            <Table.Row key={list.filename}>
                                                <Table.Cell style={{ fontWeight: 'bold' }}>
                                                    {list.filename}
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

                    {/* SEZIONE: MAIN TABLE */}
                    <Heading level={4} style={{ marginTop: 0, marginBottom: '15px' }}>
                        All Blacklisted IPs
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
                            placeholder="Search by IP, User, File, or Reason..."
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
                                    sortKey="filename"
                                    sortDir={sortKey === 'filename' ? sortDir : 'none'}
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
                                    Added On
                                </Table.HeadCell>
                            </Table.Head>
                            <Table.Body>
                                {paginatedIps.length === 0 ? (
                                    <Table.Row>
                                        <Table.Cell
                                            colSpan={6}
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
                                                  : 'No IPs found in the blacklist.'}
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
                                            <Table.Cell>
                                                {row.filename || 'Manual Entry'}
                                            </Table.Cell>
                                            <Table.Cell>{row.user || 'Unknown'}</Table.Cell>
                                            <Table.Cell>{row.reason || '-'}</Table.Cell>
                                            <Table.Cell>
                                                {formatTimestamp(row.timestamp)}
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

export default ManualBlacklist;
