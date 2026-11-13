const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { merge: webpackMerge } = require('webpack-merge');
const baseConfig = require('@splunk/webpack-configs/base.config').default;

const DEBUG = process.env.NODE_ENV !== 'production';

module.exports = webpackMerge(baseConfig, {
    entry: path.join(__dirname, 'demo'),
    plugins: [
        new HtmlWebpackPlugin({
            hash: true,
            template: path.join(__dirname, 'standalone/index.html'),
        }),
    ],
    devtool: DEBUG ? 'eval-source-map' : false,
    module: {
        rules: [{ test: /\.css$/, use: 'css-loader' }],
    },
});
