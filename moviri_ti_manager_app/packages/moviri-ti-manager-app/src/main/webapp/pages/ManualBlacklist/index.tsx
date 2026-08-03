import React from 'react';
import layout from '@splunk/react-page/18';
import ManualBlacklist from '@splunk/manual-blacklist';
import { getUserTheme } from '@splunk/splunk-utils/themes';
import { StyledContainer } from './Styles';

getUserTheme()
    .then((theme) => {
        layout(
            <StyledContainer>
                <ManualBlacklist />
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
