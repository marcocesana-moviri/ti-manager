import React, { useState, useEffect, useRef } from 'react';
import Button from '@splunk/react-ui/Button';
import Text from '@splunk/react-ui/Text';
import Table from '@splunk/react-ui/Table';

import { defaultFetchInit } from '@splunk/splunk-utils/fetch';

import { StyledContainer, StyledGreeting } from './ManualBlacklistStyles';

const APP_NAME = 'moviri-ti-manager-app';
const COLLECTION_NAME = 'manual_blacklist';

// Dynamically extract the locale (e.g., 'en-US', 'it-IT') to build the correct path
const locale = window.location.pathname.split('/')[1] || 'en-US';
const KV_STORE_URL = `/${locale}/splunkd/__raw/servicesNS/nobody/${APP_NAME}/storage/collections/data/${COLLECTION_NAME}`;

interface IPRow {
    _key: string;
    ip: string;
    user: string;
    reason: string;
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
    const cidrRegex =
        /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\/([0-9]|[1-2][0-9]|3[0-2])$/;
    return cidrRegex.test(cidr);
};

const ManualBlacklist: React.FC = () => {
    const [ips, setIps] = useState<IPRow[]>([]);

    // Form states
    const [newIp, setNewIp] = useState<string>('');
    const [newUser, setNewUser] = useState<string>('');
    const [newReason, setNewReason] = useState<string>('');

    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [error, setError] = useState<string | null>(null);

    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        fetchIps();
    }, []);

    const fetchIps = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const response = await splunkFetch(KV_STORE_URL);

            if (response.ok) {
                const data: IPRow[] = await response.json();
                setIps(data);
            } else {
                const errorText = await response.text();
                setError(`Failed to fetch data (${response.status}): ${errorText}`);
            }
        } catch (err: any) {
            setError(`Network error while fetching data: ${err.message || String(err)}`);
        } finally {
            setIsLoading(false);
        }
    };

    // Duplicate check logic for the UI
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
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ip: trimmedIp,
                    user: newUser.trim() || 'Unknown',
                    reason: newReason.trim() || 'No reason provided',
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

    const handleRemoveIp = async (key: string) => {
        setError(null);
        setIsLoading(true);
        try {
            const response = await splunkFetch(`${KV_STORE_URL}/${key}`, {
                method: 'DELETE',
            });

            if (response.ok) {
                await fetchIps();
            } else {
                const errorText = await response.text();
                setError(`Failed to remove IP (${response.status}): ${errorText}`);
                setIsLoading(false);
            }
        } catch (err: any) {
            setError(`Network error while removing: ${err.message || String(err)}`);
            setIsLoading(false);
        }
    };

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async (e) => {
            const text = e.target?.result as string;
            if (text) {
                await processBulkIps(text);
            }
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        };
        reader.readAsText(file);
    };

    const processBulkIps = async (text: string) => {
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

        // Parse and validate each line
        const parsedData = lines.map((line) => {
            const parts = line.split(',');
            return {
                ip: parts[0]?.trim() || '',
                user: parts[1]?.trim() || newUser.trim() || 'Unknown',
                reason: parts[2]?.trim() || newReason.trim() || 'Bulk upload',
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

        // --- Deduplication Logic ---
        const existingIps = new Set(ips.map((row) => row.ip));
        const uniqueParsedData = [];
        const seenInFile = new Set();

        for (const entry of parsedData) {
            // Skip if it's already in Splunk OR if it's duplicated within the file itself
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

        let hasErrors = false;

        for (const entry of uniqueParsedData) {
            try {
                const response = await splunkFetch(KV_STORE_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(entry),
                });

                if (!response.ok) {
                    hasErrors = true;
                    console.error(`Error uploading IP ${entry.ip}`);
                }
            } catch (err) {
                hasErrors = true;
                console.error(`Network error on ${entry.ip}:`, err);
            }
        }

        if (hasErrors) {
            setError('Some IPs were not saved successfully. Check the data or console logs.');
        }

        await fetchIps();
    };

    return (
        <StyledContainer>
            <StyledGreeting data-testid="greeting">Manual IP Blacklist Management</StyledGreeting>

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

            <div style={{ marginBottom: '20px' }}>
                <div
                    style={{
                        display: 'flex',
                        gap: '10px',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        marginBottom: '10px',
                    }}
                >
                    <Text
                        value={newIp}
                        onChange={(e, { value }: { value: string }) => setNewIp(value)}
                        placeholder="IP (e.g. 192.168.1.0/24)"
                        error={!isFormatValid || isDuplicate}
                        style={{ width: '200px' }}
                    />
                    <Text
                        value={newUser}
                        onChange={(e, { value }: { value: string }) => setNewUser(value)}
                        placeholder="User (Optional)"
                        style={{ width: '150px' }}
                    />
                    <Text
                        value={newReason}
                        onChange={(e, { value }: { value: string }) => setNewReason(value)}
                        placeholder="Reason (Optional)"
                        style={{ width: '250px' }}
                    />
                    <Button
                        label="Add IP"
                        appearance="primary"
                        onClick={handleAddIp}
                        disabled={isInputEmpty || !isFormatValid || isDuplicate || isLoading}
                    />

                    <input
                        type="file"
                        accept=".txt,.csv"
                        ref={fileInputRef}
                        style={{ display: 'none' }}
                        onChange={handleFileChange}
                    />

                    <Button
                        label="Upload CSV/TXT"
                        appearance="secondary"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isLoading}
                    />
                </div>

                {/* Errori mostrati sotto gli input a seconda del caso */}
                {!isFormatValid && (
                    <div style={{ color: '#d30909', fontSize: '12px' }}>
                        Invalid CIDR format. Ensure you provide an IP and a subnet mask (e.g.,
                        192.168.1.0/24).
                    </div>
                )}
                {isFormatValid && isDuplicate && (
                    <div style={{ color: '#d30909', fontSize: '12px', fontWeight: 'bold' }}>
                        This IP is already in the blacklist.
                    </div>
                )}
            </div>

            <Table stripeRows>
                <Table.Head>
                    <Table.HeadCell>IP Address (CIDR)</Table.HeadCell>
                    <Table.HeadCell>User</Table.HeadCell>
                    <Table.HeadCell>Reason</Table.HeadCell>
                    <Table.HeadCell style={{ width: '120px' }}>Actions</Table.HeadCell>
                </Table.Head>
                <Table.Body>
                    {ips.length === 0 ? (
                        <Table.Row>
                            <Table.Cell colSpan={4} style={{ textAlign: 'center' }}>
                                {isLoading ? 'Loading...' : 'No IPs found in the blacklist.'}
                            </Table.Cell>
                        </Table.Row>
                    ) : (
                        ips.map((row) => (
                            <Table.Row key={row._key}>
                                <Table.Cell>{row.ip}</Table.Cell>
                                <Table.Cell>{row.user || 'Unknown'}</Table.Cell>
                                <Table.Cell>{row.reason || '-'}</Table.Cell>
                                <Table.Cell>
                                    <Button
                                        label="Remove"
                                        appearance="destructive"
                                        onClick={() => handleRemoveIp(row._key)}
                                        disabled={isLoading}
                                    />
                                </Table.Cell>
                            </Table.Row>
                        ))
                    )}
                </Table.Body>
            </Table>
        </StyledContainer>
    );
};

export default ManualBlacklist;
