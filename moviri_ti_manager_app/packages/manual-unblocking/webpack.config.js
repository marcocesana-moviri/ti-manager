const path = require('path');
const { merge: webpackMerge } = require('webpack-merge');
const baseComponentConfig = require('@splunk/webpack-configs/component.config').default;

module.exports = webpackMerge(baseComponentConfig, {
    entry: {
        ManualUnblocking: path.join(__dirname, 'src/ManualUnblocking.tsx'),
    },
    output: {
        path: path.join(__dirname),
    },
});
