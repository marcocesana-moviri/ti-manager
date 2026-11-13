import React from 'react';
import layout from '@splunk/react-page/18';
import ManualUnblocking from '@splunk/manual-unblocking';
import { getUserTheme } from '@splunk/splunk-utils/themes';
import { StyledContainer } from './Styles';

getUserTheme()
    .then((theme) => {
        layout(
            <StyledContainer>
                <ManualUnblocking />
            </StyledContainer>,
            {
                theme,
            }
        );
    })
    .catch((e) => {
        const errorEl = document.createElement('span');
        errorEl.innerHTML = e;
        document.body.appendChild(errorEl);
    });
